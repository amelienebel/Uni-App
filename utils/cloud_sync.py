"""Cloud-Speicher: spiegelt den Ordner data/ in ein privates GitHub-Repository.

Wozu? Läuft die App online (z. B. Streamlit Community Cloud), wird der Ordner data/
bei jedem Neustart geleert. Mit dieser Synchronisierung bleiben Notizen, Lernkarten,
Uploads und Einstellungen dauerhaft erhalten – und Handy und Mac sehen denselben Stand.

Aktiv nur, wenn GITHUB_TOKEN und GITHUB_DATA_REPO (z. B. "name/uni-app-daten")
in den Secrets bzw. der .env stehen. Ohne diese Angaben bleibt alles rein lokal.

Ablauf:
- Beim Start der App werden die Lerndaten (JSON) aus dem Repository nach data/ geladen. Große Dateien
  (PDFs, Fotos, Podcasts unter uploads/) werden erst geholt, wenn sie wirklich gebraucht werden –
  so bleibt der Start auch mit vielen Unterlagen schnell.
- Jede Änderung wird vorgemerkt und gebündelt hochgeladen: sobald 15 Sekunden lang nichts
  mehr an der Datei geändert wurde, spätestens aber nach 60 Sekunden. Das schont die
  Commit-Limits von GitHub bei schnellen Folgeänderungen (z. B. beim Kartenlernen).
"""

from __future__ import annotations

import base64
import hashlib
import threading
import time
from pathlib import Path
from urllib.parse import quote

import requests

from utils.config import get_secret

API = "https://api.github.com"
DEBOUNCE_SECONDS = 15
MAX_WAIT_SECONDS = 60
MAX_FAILURES = 5
LAZY_PREFIXES = ("uploads/",)  # erst bei Bedarf herunterladen


class CloudSyncError(Exception):
    """Verständliche Fehlermeldung für die Oberfläche."""


class ConflictError(CloudSyncError):
    """Die bekannte Dateiversion passt nicht zur Version im Repository."""


def git_blob_sha(content: bytes) -> str:
    """SHA, den GitHub für eine Datei mit diesem Inhalt vergibt (Git-Blob-Hash)."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


class GitHubStore:
    """Minimaler Zugriff auf die Dateien eines GitHub-Repositorys."""

    def __init__(self, repo: str, token: str, branch: str | None = None):
        self.repo = repo.strip().strip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self.branch = branch or self._default_branch()

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            return self.session.request(method, f"{API}{path}", timeout=60, **kwargs)
        except requests.RequestException as exc:
            raise CloudSyncError(f"Keine Verbindung zu GitHub: {exc}") from exc

    def _default_branch(self) -> str:
        resp = self._request("GET", f"/repos/{self.repo}")
        if resp.status_code == 401:
            raise CloudSyncError("Der GitHub-Token ist ungültig oder abgelaufen.")
        if resp.status_code == 404:
            raise CloudSyncError(f"Repository „{self.repo}“ nicht gefunden – Name prüfen und ob der Token "
                                 "Zugriff auf genau dieses Repository hat.")
        if not resp.ok:
            raise CloudSyncError(f"GitHub-Fehler {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("default_branch") or "main"

    def list_files(self) -> dict[str, str]:
        resp = self._request("GET", f"/repos/{self.repo}/git/trees/{quote(self.branch)}", params={"recursive": "1"})
        if resp.status_code in (404, 409):  # leeres Repository
            return {}
        if not resp.ok:
            raise CloudSyncError(f"Dateiliste konnte nicht geladen werden ({resp.status_code}).")
        return {item["path"]: item["sha"] for item in resp.json().get("tree", []) if item.get("type") == "blob"}

    def download(self, sha: str) -> bytes:
        resp = self._request("GET", f"/repos/{self.repo}/git/blobs/{sha}")
        if not resp.ok:
            raise CloudSyncError(f"Datei konnte nicht geladen werden ({resp.status_code}).")
        return base64.b64decode(resp.json()["content"])

    def upload(self, path: str, content: bytes, sha: str | None) -> str:
        body = {"message": f"Update {path}", "content": base64.b64encode(content).decode(), "branch": self.branch}
        if sha:
            body["sha"] = sha
        resp = self._request("PUT", f"/repos/{self.repo}/contents/{quote(path)}", json=body)
        if resp.status_code in (409, 422):
            raise ConflictError(resp.text[:200])
        if not resp.ok:
            raise CloudSyncError(f"Hochladen von {path} fehlgeschlagen ({resp.status_code}): {resp.text[:200]}")
        return resp.json()["content"]["sha"]

    def delete(self, path: str, sha: str) -> None:
        body = {"message": f"Delete {path}", "sha": sha, "branch": self.branch}
        resp = self._request("DELETE", f"/repos/{self.repo}/contents/{quote(path)}", json=body)
        if resp.status_code == 404:
            return
        if resp.status_code in (409, 422):
            raise ConflictError(resp.text[:200])
        if not resp.ok:
            raise CloudSyncError(f"Löschen von {path} fehlgeschlagen ({resp.status_code}).")


class CloudSync:
    def __init__(self, store, data_dir: Path):
        self.store = store
        self.data_dir = Path(data_dir)
        self.shas: dict[str, str] = {}
        self.pending: dict[str, tuple[float, float]] = {}
        self.failures: dict[str, int] = {}
        self.last_error: str | None = None
        self.last_sync: float | None = None
        self._lock = threading.Lock()
        self._proc_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # -- Start ----------------------------------------------------------------
    def pull(self) -> int:
        """Lädt alle Dateien aus dem Repository, die lokal fehlen oder abweichen."""
        remote = self.store.list_files()
        downloaded = 0
        for rel, sha in remote.items():
            if rel.startswith(".") or rel.lower() == "readme.md" or ".." in Path(rel).parts:
                continue
            local = self.data_dir / rel
            if rel.startswith(LAZY_PREFIXES):
                continue  # wird bei Bedarf über fetch() geholt
            if local.exists() and git_blob_sha(local.read_bytes()) == sha:
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(self.store.download(sha))
            downloaded += 1
        self.shas = remote
        self.last_sync = time.time()
        return downloaded

    def fetch(self, rel: str) -> bool:
        """Lädt eine einzelne Datei aus dem Repository, falls sie lokal fehlt."""
        sha = self.shas.get(rel)
        local = self.data_dir / rel
        if local.exists() or not sha:
            return local.exists()
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_name(f".dl-{local.name}")
        tmp.write_bytes(self.store.download(sha))
        tmp.replace(local)
        return True

    def fetch_all(self) -> None:
        for rel in list(self.shas):
            if rel.startswith(LAZY_PREFIXES):
                self.fetch(rel)

    # -- Änderungen ---------------------------------------------------------------
    def mark_changed(self, path: Path) -> None:
        try:
            rel = Path(path).resolve().relative_to(self.data_dir.resolve()).as_posix()
        except ValueError:
            return
        if Path(rel).name.startswith("."):
            return
        now = time.monotonic()
        with self._lock:
            first = self.pending.get(rel, (now, now))[0]
            self.pending[rel] = (first, now)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._worker, name="cloud-sync", daemon=True)
                self._thread.start()

    def _ready(self, force: bool = False) -> list[str]:
        now = time.monotonic()
        with self._lock:
            ready = [rel for rel, (first, last) in self.pending.items()
                     if force or now - last >= DEBOUNCE_SECONDS or now - first >= MAX_WAIT_SECONDS]
            for rel in ready:
                del self.pending[rel]
        return ready

    def _worker(self) -> None:
        while True:
            time.sleep(1)
            for rel in self._ready():
                with self._proc_lock:
                    self._process(rel)

    def flush(self) -> None:
        """Lädt alle vorgemerkten Änderungen sofort hoch."""
        for rel in self._ready(force=True):
            with self._proc_lock:
                self._process(rel)

    def _process(self, rel: str, retry: bool = True) -> None:
        local = self.data_dir / rel
        try:
            if local.exists():
                content = local.read_bytes()
                if self.shas.get(rel) != git_blob_sha(content):
                    self.shas[rel] = self.store.upload(rel, content, self.shas.get(rel))
            elif rel in self.shas:
                self.store.delete(rel, self.shas.pop(rel))
            self.failures.pop(rel, None)
            self.last_sync = time.time()
            if not self.failures:
                self.last_error = None
        except ConflictError:
            if retry:
                # Version im Repository hat sich geändert -> aktuelle Versionsliste holen und erneut versuchen
                try:
                    self.shas.update(self.store.list_files())
                except CloudSyncError as exc:
                    self._fail(rel, str(exc))
                    return
                self._process(rel, retry=False)
            else:
                self._fail(rel, f"Konflikt beim Speichern von {rel}.")
        except CloudSyncError as exc:
            self._fail(rel, str(exc))
        except OSError as exc:
            self._fail(rel, f"Datei {rel} konnte nicht gelesen werden: {exc}")

    def _fail(self, rel: str, message: str) -> None:
        self.failures[rel] = self.failures.get(rel, 0) + 1
        self.last_error = message
        if self.failures[rel] < MAX_FAILURES:
            now = time.monotonic()
            with self._lock:
                self.pending.setdefault(rel, (now, now))

    def status(self) -> dict:
        with self._lock:
            pending = len(self.pending)
        return {"pending": pending, "error": self.last_error, "last_sync": self.last_sync}


# ---------------------------------------------------------------------------
# Globale Instanz (eine pro laufender App, gemeinsam für alle Geräte)
# ---------------------------------------------------------------------------

_sync: CloudSync | None = None
_init_error: str | None = None
_init_lock = threading.Lock()


def is_configured() -> bool:
    return bool(get_secret("GITHUB_TOKEN") and get_secret("GITHUB_DATA_REPO"))


def ensure_started(data_dir: Path) -> None:
    """Verbindet sich einmalig mit GitHub und lädt die gespeicherten Daten."""
    global _sync, _init_error
    if _sync is not None or _init_error is not None or not is_configured():
        return
    with _init_lock:
        if _sync is not None or _init_error is not None:
            return
        try:
            store = GitHubStore(get_secret("GITHUB_DATA_REPO"), get_secret("GITHUB_TOKEN"))
            sync = CloudSync(store, data_dir)
            sync.pull()
            _sync = sync
        except CloudSyncError as exc:
            _init_error = str(exc)


def _rel(path: Path) -> str | None:
    if _sync is None:
        return None
    try:
        return Path(path).resolve().relative_to(_sync.data_dir.resolve()).as_posix()
    except ValueError:
        return None


def ensure_local(path: Path) -> None:
    """Holt eine Datei aus dem Cloud-Speicher, wenn sie lokal (noch) fehlt."""
    rel = _rel(path)
    if rel and not Path(path).exists():
        try:
            _sync.fetch(rel)
        except CloudSyncError:
            pass


def available(path: Path) -> bool:
    """Gibt es die Datei – lokal oder im Cloud-Speicher?"""
    if Path(path).exists():
        return True
    rel = _rel(path)
    return bool(rel and rel in _sync.shas)


def fetch_all() -> None:
    """Alle Dateien lokal verfügbar machen (z. B. vor einem vollständigen Backup)."""
    if _sync is not None:
        try:
            _sync.fetch_all()
        except CloudSyncError:
            pass


def notify_changed(path: Path) -> None:
    if _sync is not None:
        _sync.mark_changed(path)


def flush() -> None:
    if _sync is not None:
        _sync.flush()


def status() -> dict | None:
    """None = Cloud-Speicher nicht eingerichtet."""
    if _init_error:
        return {"pending": 0, "error": f"Cloud-Speicher nicht verbunden: {_init_error}", "last_sync": None,
                "fatal": True}
    if _sync is None:
        return None
    return {**_sync.status(), "fatal": False}
