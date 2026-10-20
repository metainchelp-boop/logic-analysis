"""Dedicated saved-search cache. HTTP reads only selected SQLite rows, never source files."""
from datetime import datetime
import hashlib
import json
import re

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS naver_auto_market_source (
        store_key TEXT PRIMARY KEY,generation TEXT NOT NULL,payload_json TEXT NOT NULL)""",
)
_HEADER = "market-export:header"
_ROW_BYTES = 512 * 1024


def _raw(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_raw(value).encode()).hexdigest()


class MarketStorage:
    def record_market_export(self, bundle, now, *, status=None):
        """All-or-none validation precedes an atomic generation/header change."""
        from . import market_evidence as ME, store as S
        self._need_writer()
        self._not_future(now, "검색 표본 캐시 시각")
        if status not in (None, "unavailable", "invalid") or status is not None and bundle is not None:
            raise S.StoreRefused("검색 표본 캐시 상태를 확인해 주세요")
        if status is None:
            try:
                clean = ME.validate_bundle(bundle, now)
            except (ME.EvidenceInvalid, ValueError, TypeError, RecursionError):
                raise S.StoreRefused("검색 표본 원천 형식을 확인해 주세요") from None
            stores = sorted(clean["stores"], key=lambda row: row["store_key"])
            if any(len(_raw(row).encode()) > _ROW_BYTES for row in stores):
                raise S.StoreRefused("검색 표본의 업체별 저장 크기를 확인해 주세요")
            generation = _digest(stores)
            header = {"version": 1, "status": "ok", "exported_at": clean["exported_at"], "generation": generation}
        else:
            stores = []
            header = {"version": 1, "status": status, "exported_at": None, "generation": None}
        with self._tx() as connection:
            body = _raw(header)
            if self._get_meta(connection, _HEADER) == body:
                return {"state": header["status"], "changed": False}
            old = self._market_header()
            if header["status"] == "ok" and (old is None or old["generation"] != generation or old["status"] != "ok"):
                for row in stores:
                    connection.execute("""INSERT INTO naver_auto_market_source(store_key,generation,payload_json)
                        VALUES(?,?,?) ON CONFLICT(store_key) DO UPDATE SET
                        generation=excluded.generation,payload_json=excluded.payload_json""",
                        (row["store_key"], generation, _raw(row)))
            self._set_meta(connection, _HEADER, body)
        return {"state": header["status"], "changed": True}

    def _market_header(self):
        row = self._conn.execute("SELECT length(value),substr(value,1,4097) FROM naver_auto_meta WHERE key=?", (_HEADER,)).fetchone()
        if row is None or row[0] > 4096:
            return None
        try:
            value = json.loads(row[1])
            if (not isinstance(value, dict) or set(value) != {"version", "status", "exported_at", "generation"}
                    or type(value["version"]) is not int or value["version"] != 1
                    or value["status"] not in {"ok", "unavailable", "invalid"}):
                return None
            if value["status"] == "ok":
                at = datetime.fromisoformat(value["exported_at"])
                if at.utcoffset() is None or not isinstance(value["generation"], str) or not re.fullmatch("[0-9a-f]{64}", value["generation"]):
                    return None
            elif value["exported_at"] is not None or value["generation"] is not None:
                return None
            return value
        except (ValueError, TypeError, OverflowError, RecursionError):
            return None

    def _market_selection(self, store_key, now):
        from . import market_evidence as ME
        header = self._market_header()
        if header is None or header["status"] == "unavailable":
            return ME.select(None, store_key, now)
        if header["status"] == "invalid":
            return ME.select({}, store_key, now)
        row = self._conn.execute("""SELECT length(CAST(payload_json AS BLOB)),substr(CAST(payload_json AS BLOB),1,?)
            FROM naver_auto_market_source WHERE store_key=? AND generation=?""",
            (_ROW_BYTES + 1, store_key, header["generation"])).fetchone()
        try:
            if row and row[0] > _ROW_BYTES:
                return ME.select({}, store_key, now)
            stores = [] if row is None else [json.loads(row[1])]
            if stores and stores[0].get("store_key") != store_key:
                return ME.select({}, store_key, now)
            return ME.select({"schema_version": 1, "complete": True, "exported_at": header["exported_at"], "stores": stores}, store_key, now)
        except (ValueError, TypeError, RecursionError, AttributeError):
            return ME.select({}, store_key, now)

    def market_source(self, possibility_id, account_key, now, *, _binding=None):
        """Bind a saved search sample to current ERP ownership and an individual account."""
        from . import market_evidence as ME
        binding = _binding if _binding is not None else self._evidence_binding(possibility_id, account_key, now)
        store_key = binding["store_key"]
        selected = self._market_selection(store_key, now) if store_key is not None else ME.select(None, None, now)
        revision = None
        if selected["status"] == "ready":
            revision = self._evidence_revision(binding)
            if revision is None:
                selected = ME.select(None, store_key, now)
        fingerprint = _digest({"possibility_id": possibility_id, "account_key": account_key,
            "store_key": store_key, "stage_revision": revision, "source_fingerprint": selected["source_fingerprint"]})
        return {"context": ME.model_context(selected), "fingerprint": fingerprint}

    def _strategy_evidence(self, possibility_id, account_key, now):
        binding = self._evidence_binding(possibility_id, account_key, now)
        return (self.product_source(possibility_id, account_key, now, _binding=binding),
                self.market_source(possibility_id, account_key, now, _binding=binding))

    def _market_strategy_ref(self, connection, identity, version):
        row = connection.execute("SELECT length(value),substr(value,1,257) FROM naver_auto_meta WHERE key=?",
            (f"market-strategy:{identity}:{version}",)).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row[1])
            if row[0] > 256 or not isinstance(value, dict) or set(value) != {"fingerprint"} \
                    or not isinstance(value["fingerprint"], str) or not re.fullmatch("[0-9a-f]{64}", value["fingerprint"]):
                return {"fingerprint": None}
            return value
        except (ValueError, TypeError):
            return {"fingerprint": None}

    def _save_market_strategy_ref(self, connection, identity, version, fingerprint):
        self._set_meta(connection, f"market-strategy:{identity}:{version}", _raw({"fingerprint": fingerprint}))
