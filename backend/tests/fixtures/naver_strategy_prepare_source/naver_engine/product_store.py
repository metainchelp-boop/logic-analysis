"""Dedicated saved-product cache. Web reads never open the logic DB or export file."""
from datetime import datetime
import hashlib
import json
import re

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS naver_auto_product_link (
        possibility_id INTEGER PRIMARY KEY,store_key TEXT,stage_as_of TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_product_source (
        store_key TEXT PRIMARY KEY,generation TEXT NOT NULL,payload_json TEXT NOT NULL)""",
)
_HEADER = "product-export:header"
_ROW_BYTES = 65536


def _raw(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_raw(value).encode()).hexdigest()


class ProductStorage:
    def _record_product_link(self, connection, possibility_id, store_key, at):
        connection.execute("""INSERT INTO naver_auto_product_link(possibility_id,store_key,stage_as_of)
            VALUES(?,?,?) ON CONFLICT(possibility_id) DO UPDATE SET
            store_key=excluded.store_key,stage_as_of=excluded.stage_as_of""", (possibility_id, store_key, at))

    def record_product_export(self, bundle, now, *, status=None):
        """Validate the complete bundle before a single atomic cache update; no source DB I/O."""
        from . import product_evidence as PE, store as S
        self._need_writer()
        self._not_future(now, "상품 캐시 시각")
        if status not in (None, "unavailable", "invalid") or status is not None and bundle is not None:
            raise S.StoreRefused("상품 캐시 상태를 확인해 주세요")
        if status is None:
            try:
                clean = PE.validate_bundle(bundle, now)
            except (PE.EvidenceInvalid, ValueError, TypeError, RecursionError):
                raise S.StoreRefused("상품 캐시 원천 형식을 확인해 주세요") from None
            stores = sorted(clean["stores"], key=lambda row: row["store_key"])
            generation = _digest(stores)
            header = {"version": 1, "status": "ok", "exported_at": clean["exported_at"], "generation": generation}
        else:
            stores = []
            header = {"version": 1, "status": status, "exported_at": None, "generation": None}
        with self._tx() as connection:
            previous = self._get_meta(connection, _HEADER)
            body = _raw(header)
            if previous == body:
                return {"state": header["status"], "changed": False}
            old = self._product_header()
            # A renewed export timestamp alone does not rewrite store rows or invalidate proofs.
            if header["status"] == "ok" and (old is None or old["generation"] != generation or old["status"] != "ok"):
                for row in stores:
                    connection.execute("""INSERT INTO naver_auto_product_source(store_key,generation,payload_json)
                        VALUES(?,?,?) ON CONFLICT(store_key) DO UPDATE SET
                        generation=excluded.generation,payload_json=excluded.payload_json""",
                        (row["store_key"], generation, _raw(row)))
            self._set_meta(connection, _HEADER, body)
        return {"state": header["status"], "changed": True}

    def _product_header(self):
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

    def _product_selection(self, store_key, now):
        from . import product_evidence as PE
        header = self._product_header()
        if header is None or header["status"] == "unavailable":
            return PE.select(None, store_key, now)
        if header["status"] == "invalid":
            return PE.select({}, store_key, now)
        # Only the selected store is loaded. Old generations cannot reappear after removal/failure.
        row = self._conn.execute("""SELECT length(payload_json),substr(payload_json,1,?)
            FROM naver_auto_product_source WHERE store_key=? AND generation=?""",
            (_ROW_BYTES + 1, store_key, header["generation"])).fetchone()
        try:
            if row and row[0] > _ROW_BYTES:
                return PE.select({}, store_key, now)
            stores = [] if row is None else [json.loads(row[1])]
            if stores and stores[0].get("store_key") != store_key:
                return PE.select({}, store_key, now)
            return PE.select({"schema_version": 1, "complete": True, "exported_at": header["exported_at"], "stores": stores}, store_key, now)
        except (ValueError, TypeError, RecursionError, AttributeError):
            return PE.select({}, store_key, now)

    def _evidence_binding(self, possibility_id, account_key, now):
        """One request-local link/authority memo, shared by separate evidence selectors."""
        from . import product_evidence as PE, store as S
        S._pos_int(possibility_id, "업체")
        if not isinstance(account_key, str) or not re.fullmatch("[0-9a-f]{64}", account_key):
            raise S.StoreRefused("상품 자료의 개별 계정 범위를 확인해 주세요")
        link = self._conn.execute("""SELECT l.store_key,l.stage_as_of FROM naver_auto_product_link l
            JOIN naver_auto_prospect p ON p.possibility_id=l.possibility_id
            WHERE l.possibility_id=? AND p.present=1 AND p.stage_conflict=0 AND l.stage_as_of=p.stage_synced_at""",
            (possibility_id,)).fetchone()
        store_key = link[0] if link is not None else None
        if store_key is not None and PE.canonical_store(store_key) != store_key:
            store_key = None
        return {"possibility_id": possibility_id, "account_key": account_key, "store_key": store_key,
                "stage_as_of": link[1] if link is not None else None, "at": now,
                "resolved": False, "revision": None}

    def _evidence_revision(self, binding):
        from . import report_views as RV, store as S, management_store as MS, handles as H
        if binding["resolved"]:
            return binding["revision"]
        binding["resolved"] = True
        now = binding["at"]
        try:
            linked_at = datetime.fromisoformat(binding["stage_as_of"])
            link_current = linked_at.utcoffset() is not None and now - linked_at <= H.STAGE_MAX_AGE \
                and linked_at - now <= S.FUTURE_SLACK
        except (TypeError, ValueError, OverflowError):
            link_current = False
        authority = next((row for cid, row in MS.snapshot(self, now).items()
            if RV.account_key(cid) == binding["account_key"] and row["possibility_id"] == binding["possibility_id"]
            and row["source_current"]), None) if link_current else None
        binding["revision"] = authority["stage_revision"] if authority is not None else None
        return binding["revision"]

    def product_source(self, possibility_id, account_key, now, *, _binding=None):
        """Current PID/account/link binding plus a closed model context; no actor data on the wire."""
        from . import product_evidence as PE
        binding = _binding if _binding is not None else self._evidence_binding(possibility_id, account_key, now)
        store_key = binding["store_key"]
        selected = self._product_selection(store_key, now) if store_key is not None else PE.select(None, None, now)
        revision = None
        if selected["status"] == "ready":
            revision = self._evidence_revision(binding)
            if revision is None:
                selected = PE.select(None, store_key, now)
        context = PE.model_context(selected)
        fingerprint = _digest({"possibility_id": possibility_id, "account_key": account_key,
            "store_key": store_key, "stage_revision": revision, "source_fingerprint": selected["source_fingerprint"]})
        return {"context": context, "fingerprint": fingerprint}

    def _product_strategy_ref(self, connection, identity, version):
        row = connection.execute("SELECT length(value),substr(value,1,257) FROM naver_auto_meta WHERE key=?",
            (f"product-strategy:{identity}:{version}",)).fetchone()
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

    def _save_product_strategy_ref(self, connection, identity, version, fingerprint):
        self._set_meta(connection, f"product-strategy:{identity}:{version}", _raw({"fingerprint": fingerprint}))
