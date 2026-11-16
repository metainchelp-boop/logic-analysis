"""SEO 추천 원본과 직원 승인본 보존. 호출자가 권한과 트랜잭션을 관리한다."""
import hashlib
import json
from datetime import datetime

FIELDS = ("product_name", "tags", "page_title", "meta_description")
LIMITS = {"product_name": 100, "page_title": 100, "meta_description": 160}


class ReviewError(ValueError):
    pass


def version(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def init_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS seo_generations (
            generation_id TEXT PRIMARY KEY, client_id INTEGER,
            keyword TEXT NOT NULL, product_url TEXT NOT NULL,
            result_json TEXT NOT NULL, created_by TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS seo_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id TEXT NOT NULL UNIQUE,
            result_id INTEGER NOT NULL UNIQUE, approved_json TEXT NOT NULL,
            decisions_json TEXT NOT NULL, reviewed_by TEXT NOT NULL, reviewed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS seo_rules_history (
            version TEXT PRIMARY KEY, rules_text TEXT NOT NULL,
            recorded_at TEXT NOT NULL, recorded_by TEXT
        );
    """)


def remember_rules(conn, text, who):
    conn.execute("INSERT OR IGNORE INTO seo_rules_history VALUES(?,?,?,?)",
                 (version(text), text, datetime.now().isoformat(), str(who)))


def record_generation(conn, data, client_id, who):
    conn.execute("INSERT INTO seo_generations VALUES(?,?,?,?,?,?,?)",
                 (data["generation_id"], client_id, data["keyword"], data["product_url"],
                  dumps(data), str(who), datetime.now().isoformat()))


def clean_value(key, value, allow_unknown=False):
    if (value is None or value == "") and allow_unknown:
        return None
    if key == "tags":
        if not isinstance(value, list) or len(value) > 10:
            raise ReviewError("태그는 최대 10개의 목록이어야 합니다.")
        result = []
        for tag in value:
            if not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 50:
                raise ReviewError("태그 내용을 확인해 주세요.")
            tag = tag.strip().lstrip("#")
            if not tag:
                raise ReviewError("빈 태그는 저장할 수 없습니다.")
            if tag not in result:
                result.append(tag)
        return result
    if not isinstance(value, str) or len(value.strip()) > LIMITS[key]:
        raise ReviewError("상품명·페이지 제목·메타 설명의 형식 또는 길이를 확인해 주세요.")
    if key == "product_name" and not value.strip():
        raise ReviewError("승인할 상품명은 비워둘 수 없습니다.")
    return value.strip()


def save_review(conn, req, who):
    if req.reviewed is not True:
        raise ReviewError("네 항목을 검토한 뒤 확인란을 선택해 주세요.")
    row = conn.execute("SELECT * FROM seo_generations WHERE generation_id=?", (req.generation_id,)).fetchone()
    if row is None:
        raise ReviewError("추천 원본을 찾지 못했습니다. 다시 생성해 주세요.")
    if (row["client_id"] != req.client_id or row["keyword"] != req.keyword.strip()
            or row["product_url"] != req.product_url.strip()):
        raise ReviewError("추천 당시 업체·상품·키워드와 다릅니다. 다시 생성해 주세요.")
    original = json.loads(row["result_json"])
    decisions = req.decisions
    if not isinstance(decisions, dict) or set(decisions) != set(FIELDS):
        raise ReviewError("네 항목의 채택·수정·보류를 선택해 주세요.")
    approved = {}
    for key in FIELDS:
        decision = decisions[key]
        if decision == "hold":
            approved[key] = original["current_values"].get(key)
        elif decision == "adopt":
            approved[key] = clean_value(key, original["recommendation"][key])
        elif decision == "edit":
            approved[key] = clean_value(key, (req.approved_values or {}).get(key))
        else:
            raise ReviewError("채택·수정·보류 중에서 선택해 주세요.")
    old = conn.execute("SELECT * FROM seo_reviews WHERE generation_id=?", (req.generation_id,)).fetchone()
    if old:
        if json.loads(old["approved_json"]) != approved or json.loads(old["decisions_json"]) != decisions:
            raise ReviewError("이미 저장된 승인본과 다릅니다. 새 추천을 생성해 주세요.")
        return old["result_id"]
    stamp = datetime.now().isoformat()
    result_id = conn.execute("""INSERT INTO client_seo_results
        (client_id,keyword,product_name,tags_json,category,rationale_json,source,created_by,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)""", (req.client_id, row["keyword"], approved["product_name"] or "",
        dumps(approved["tags"] or []), original["category"], dumps(original["rationale"]),
        "generate", str(who), stamp)).lastrowid
    conn.execute("""INSERT INTO seo_reviews
        (generation_id,result_id,approved_json,decisions_json,reviewed_by,reviewed_at) VALUES(?,?,?,?,?,?)""",
        (req.generation_id, result_id, dumps(approved), dumps(decisions), str(who), stamp))
    return result_id


def review_for_result(conn, result_id):
    row = conn.execute("""SELECT r.*,g.result_json FROM seo_reviews r JOIN seo_generations g
        ON r.generation_id=g.generation_id WHERE r.result_id=?""", (result_id,)).fetchone()
    if not row:
        return None
    original = json.loads(row["result_json"])
    return {"generation_id": row["generation_id"], "approved_values": json.loads(row["approved_json"]),
            "decisions": json.loads(row["decisions_json"]), "reviewed_by": row["reviewed_by"],
            "reviewed_at": row["reviewed_at"], "product_url": original["product_url"],
            "rules_version": original["rules_version"], "original": original}
