"""공개 포트 없이 유닉스 소켓으로만 받는 제한된 WSGI 서버."""
import fcntl
import io
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import threading
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from naver_engine.web import TRUSTED_TRANSPORT


class ServerError(RuntimeError):
    pass


class _Handler(WSGIRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()
        self.client_address = ("", 0)

    def get_environ(self):
        env = super().get_environ()
        env["REMOTE_ADDR"] = ""
        env[TRUSTED_TRANSPORT] = True
        return env

    def get_stderr(self):
        # 프레임워크가 경로·본문·토큰이 있는 예외를 표준 오류로 내보내지 않는다.
        return io.StringIO()

    def log_message(self, *args):
        pass


class _UnixServer(socketserver.ThreadingMixIn, WSGIServer):
    address_family = socket.AF_UNIX
    request_queue_size = 32
    daemon_threads = True
    block_on_close = False

    def __init__(self, path, app, capacity):
        self.slots = threading.BoundedSemaphore(capacity)
        super().__init__(path, _Handler)
        self.set_app(app)

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "naver-engine", 0
        self.setup_environ()

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass


def _socket_folder(path):
    p = Path(path)
    if not p.is_absolute() or len(os.fsencode(str(p))) > 100:
        raise ServerError("짧은 전용 소켓 절대 경로가 필요합니다")
    parent = p.parent
    if parent.resolve() != parent or not parent.is_dir():
        raise ServerError("소켓 폴더를 먼저 준비해야 합니다")
    info = parent.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o002:
        raise ServerError("소켓 폴더 소유자·권한이 잘못되었습니다")
    return p


class UnixServer:
    def __init__(self, path, app, *, capacity=16):
        if not 1 <= capacity <= 32:
            raise ServerError("동시 요청 수가 잘못되었습니다")
        self.path = _socket_folder(path)
        self._fd = None
        self._server = None
        self._thread = None
        self._inode = None
        try:
            lock = self.path.parent / ".engine.lock"
            self._fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            info = os.fstat(self._fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                raise ServerError("소켓 잠금 파일이 잘못되었습니다")
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fchmod(self._fd, 0o600)
            self._remove_stale_socket()
            self._server = _UnixServer(str(self.path), app, capacity)
            os.chmod(self.path, 0o660)
            self._inode = self.path.stat().st_ino
        except BaseException:
            self.close()
            raise

    def _remove_stale_socket(self):
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            raise ServerError("기존 파일은 소켓이 아니거나 다른 소유자입니다")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(.2)
            try:
                probe.connect(str(self.path))
            except ConnectionRefusedError:
                # 잠금까지 얻은 뒤, 살아 있지 않은 우리 소켓 하나만 지운다.
                if self.path.lstat().st_ino != info.st_ino:
                    raise ServerError("소켓이 검사 중 바뀌었습니다")
                self.path.unlink()
            else:
                raise ServerError("기존 소켓이 아직 사용 중입니다")

    def start(self):
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": .1}, daemon=True, name="naver-web")
        self._thread.start()
        return self

    def close(self):
        if self._server is not None:
            if self._thread is not None:
                self._server.shutdown()
                self._thread.join(5)
            self._server.server_close()
            self._server = None
        if self._inode is not None:
            try:
                if self.path.lstat().st_ino == self._inode:
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self._inode = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()


def health_app(status):
    """내부 확인용. 상태 코드만 반환하며 DB·자격증명·경로는 내보내지 않는다."""
    def app(env, start):
        if env.get("PATH_INFO") != "/_engine/health" or env.get("REQUEST_METHOD") != "GET":
            code, body = "404 Not Found", {"error": "not-found"}
        else:
            body = status()
            code = "503 Service Unavailable" if body.get("state") == "failed" else "200 OK"
        payload = json.dumps(body, separators=(",", ":")).encode()
        start(code, [("Content-Type", "application/json"), ("Content-Length", str(len(payload))),
                     ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")])
        return [payload]
    return app
