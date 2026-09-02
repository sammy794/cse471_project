import os
import shutil
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


def _activity_score(db_path: Path):
    """Prefer the database that contains the newest user/project activity."""
    latest = ""
    rows = 0
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        for table in (
            "users", "donations", "campaigns", "complaints_feedback",
            "aid_distributions", "volunteer_missions", "field_reports",
        ):
            try:
                rows += int(cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
            except sqlite3.Error:
                pass
        for table, column in (
            ("users", "created_at"), ("donations", "created_at"),
            ("campaigns", "created_at"), ("complaints_feedback", "created_at"),
            ("aid_distributions", "distributed_at"), ("volunteer_missions", "created_at"),
            ("field_reports", "created_at"),
        ):
            try:
                value = cur.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
                if value and str(value) > latest:
                    latest = str(value)
            except sqlite3.Error:
                pass
        con.close()
    except Exception:
        return ("", 0, 0.0)
    try:
        mtime = db_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (latest, rows, mtime)


def _find_best_existing_database(bundled_path: Path) -> Path:
    candidates = [bundled_path]
    # When a new project ZIP is extracted beside an older DisasterNet copy,
    # include those databases in the one-time migration so accounts and data
    # created in the previous copy are not lost just because the folder changed.
    try:
        downloads_like_root = Path(__file__).resolve().parents[5]
        patterns = [
            "Project_cse471*/Project cse471/disasternet/backend/disasternet.db",
            "*cse471*/Project cse471/disasternet/backend/disasternet.db",
            "*/Project cse471/disasternet/backend/disasternet.db",
        ]
        for pattern in patterns:
            for path in downloads_like_root.glob(pattern):
                if path.is_file() and path not in candidates:
                    candidates.append(path)
    except Exception:
        pass
    valid = [p for p in candidates if p.exists() and p.is_file()]
    return max(valid, key=_activity_score) if valid else bundled_path


BUNDLED_DATABASE_PATH = Path(__file__).resolve().parents[1] / "disasternet.db"

# Keep the working database outside extracted ZIP folders so registrations,
# donations, reports and all other records survive restarts and future project
# ZIP updates. DISASTERNET_DATABASE_PATH can override this location if needed.
_override = os.getenv("DISASTERNET_DATABASE_PATH")
if _override:
    DATABASE_PATH = Path(_override).expanduser().resolve()
else:
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        data_dir = Path(os.environ["LOCALAPPDATA"]) / "DisasterNet"
    else:
        data_dir = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "DisasterNet"
    data_dir.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH = data_dir / "disasternet.db"

def _initialize_persistent_database():
    """Create the shared DB once, and recover newer data from older extracted copies.

    DisasterNet project ZIPs are often extracted into a new folder.  The shared
    database under LOCALAPPDATA prevents normal restarts from losing data.  If
    an older extracted project contains newer activity than the shared DB, copy
    that complete database into the shared location before SQLAlchemy opens it.
    A backup of the previous shared DB is kept beside it.
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    source = _find_best_existing_database(BUNDLED_DATABASE_PATH)
    if not source.exists():
        return

    if not DATABASE_PATH.exists():
        shutil.copy2(source, DATABASE_PATH)
        return

    try:
        source_resolved = source.resolve()
        target_resolved = DATABASE_PATH.resolve()
    except OSError:
        source_resolved, target_resolved = source, DATABASE_PATH
    if source_resolved == target_resolved:
        return

    source_score = _activity_score(source)
    target_score = _activity_score(DATABASE_PATH)
    # A later saved activity timestamp means this extracted project was used
    # after the shared database.  Promote the whole DB so related foreign-key
    # records stay together instead of copying users without their project data.
    if source_score[0] and (not target_score[0] or source_score[0] > target_score[0]):
        backup_path = DATABASE_PATH.with_name("disasternet_before_migration.db")
        try:
            shutil.copy2(DATABASE_PATH, backup_path)
        except OSError:
            pass
        shutil.copy2(source, DATABASE_PATH)


_initialize_persistent_database()

def _normalize_payment_schema(db_path: Path):
    """Upgrade older DisasterNet databases to the provider-neutral donation schema.

    Older project copies stored payment-provider-specific columns and helper
    tables.  This migration discovers those shapes from SQLite metadata, keeps
    donation/history data, renames the two donation payment columns to generic
    names, removes obsolete simulation-only user columns, and drops obsolete
    payment helper tables that are no longer part of the application.
    """
    if not db_path.exists():
        return

    changed = False
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        table_names = {
            row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "donations" in table_names:
            info = con.execute("PRAGMA table_info(donations)").fetchall()
            columns = [row[1] for row in info]
            common = {
                "id", "campaign_id", "donor_user_id", "donor_name",
                "amount", "tracking_id", "payment_status", "created_at",
                "payment_gateway", "payment_reference", "gateway_transaction_id",
            }

            # Discover the previous transaction column by its unique index, then
            # treat the other provider-specific donation column as the reference.
            extras = [name for name in columns if name not in common]
            indexed_unique = set()
            for idx in con.execute("PRAGMA index_list(donations)").fetchall():
                idx_name, is_unique = idx[1], bool(idx[2])
                if not is_unique:
                    continue
                idx_cols = [
                    row[2] for row in con.execute(f'PRAGMA index_info("{idx_name}")').fetchall()
                ]
                indexed_unique.update(name for name in idx_cols if name in extras)

            if "gateway_transaction_id" not in columns and extras:
                tx_source = next(iter(indexed_unique), None)
                if tx_source is None and len(extras) >= 2:
                    tx_source = extras[-1]
                if tx_source:
                    con.execute(
                        f'ALTER TABLE donations RENAME COLUMN "{tx_source}" TO gateway_transaction_id'
                    )
                    changed = True
                    extras = [name for name in extras if name != tx_source]
                    columns = [
                        "gateway_transaction_id" if name == tx_source else name
                        for name in columns
                    ]

            if "payment_reference" not in columns and extras:
                ref_source = extras[0]
                con.execute(
                    f'ALTER TABLE donations RENAME COLUMN "{ref_source}" TO payment_reference'
                )
                changed = True
                columns = [
                    "payment_reference" if name == ref_source else name
                    for name in columns
                ]

            if "payment_gateway" not in columns:
                con.execute(
                    "ALTER TABLE donations ADD COLUMN payment_gateway VARCHAR NOT NULL DEFAULT 'LEGACY'"
                )
                changed = True

            # Replace any stale index name with the generic one.
            for idx in con.execute("PRAGMA index_list(donations)").fetchall():
                idx_name = idx[1]
                if idx_name.startswith("sqlite_autoindex"):
                    continue
                idx_cols = [
                    row[2] for row in con.execute(f'PRAGMA index_info("{idx_name}")').fetchall()
                ]
                if idx_cols == ["gateway_transaction_id"] and idx_name != "ix_donations_gateway_transaction_id":
                    con.execute(f'DROP INDEX IF EXISTS "{idx_name}"')
                    changed = True
            current_indexes = {row[1] for row in con.execute("PRAGMA index_list(donations)").fetchall()}
            if "ix_donations_gateway_transaction_id" not in current_indexes:
                con.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_donations_gateway_transaction_id "
                    "ON donations (gateway_transaction_id)"
                )
                changed = True

            # Existing SSLCOMMERZ donations can be identified by their payment table.
            if "sslcommerz_payments" in table_names:
                con.execute(
                    "UPDATE donations SET payment_gateway='SSLCOMMERZ' "
                    "WHERE id IN (SELECT donation_id FROM sslcommerz_payments)"
                )

        # Remove obsolete simulation-only user fields without depending on their old names.
        if "users" in table_names:
            expected_user_columns = {
                "id", "email", "hashed_password", "full_name", "role",
                "organization_name", "phone", "created_at",
            }
            user_columns = [row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()]
            for column in user_columns:
                if column not in expected_user_columns:
                    try:
                        con.execute(f'ALTER TABLE users DROP COLUMN "{column}"')
                        changed = True
                    except sqlite3.Error:
                        pass

        # Drop obsolete provider helper tables by schema signature. Current tables
        # are preserved because their columns do not match these old signatures.
        for table in list(table_names):
            if table.startswith("sqlite_"):
                continue
            cols = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()}
            old_payment_signature = {"payment_id", "merchant_invoice_number", "payer_reference", "execute_response"}
            old_refund_signature = {"payment_id", "original_trx_id", "refund_trx_id", "sku"}
            if old_payment_signature.issubset(cols) or old_refund_signature.issubset(cols):
                con.execute(f'DROP TABLE IF EXISTS "{table}"')
                changed = True

        con.commit()
        if changed:
            con.execute("VACUUM")
    finally:
        con.close()


_normalize_payment_schema(DATABASE_PATH)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
