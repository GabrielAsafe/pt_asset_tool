from __future__ import annotations

import dataclasses
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Protocol

FORMAT = "PT_LEGACY_SOD_MANAGER_V1"
APPLY_CONFIRM = "APPLY SOD CLAN UPDATE"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclasses.dataclass(frozen=True)
class SodRow:
    char_name: str
    server_time: int
    total_point: int
    success_user: int
    point: int | None = None


@dataclasses.dataclass(frozen=True)
class SodUpdate:
    clan_name: str
    old_point: int
    new_point: int
    server_time: int
    total_point: int
    success_user: int
    same_clan_participants: int
    source_character: str


class SodDataSource(Protocol):
    def runs(self, table: str) -> Iterable[SodRow]: ...
    def run_members(self, table: str, server_time: int, total_point: int, success_user: int) -> Iterable[SodRow]: ...
    def clan_for_character(self, char_name: str) -> str: ...
    def clan_point(self, clan_name: str) -> int: ...
    def update_clan_point(self, clan_name: str, point: int) -> None: ...
    def top_clan(self) -> str: ...
    def clan_money(self, clan_name: str) -> int: ...
    def update_clan_money(self, clan_name: str, money: int) -> None: ...


def validate_table_name(table: str) -> str:
    table = str(table).strip()
    if not _IDENT.fullmatch(table):
        raise ValueError("INVALID_SQL_TABLE_IDENTIFIER")
    return table


def plan_sod_updates(source: SodDataSource, table: str, *, minimum_players: int) -> dict[str, Any]:
    """Port of ClanSoDManager.Timer_Elapsed without its SQL-injection bugs.

    The original loops every qualifying row, derives the row character's clan,
    subtracts points contributed by characters of other clans in the same run,
    counts same-clan participants and raises CL.Cpoint only when the result is
    greater than the clan's current point value.
    """
    table = validate_table_name(table)
    if minimum_players < 1:
        raise ValueError("MINIMUM_PLAYERS_MUST_BE_POSITIVE")
    updates: list[SodUpdate] = []
    seen_candidates: set[tuple[int, int, int, str]] = set()
    for row in source.runs(table):
        if row.total_point <= 0 or row.success_user < minimum_players:
            continue
        clan = source.clan_for_character(row.char_name)
        if not clan:
            continue
        candidate_key = (row.server_time, row.total_point, row.success_user, clan.casefold())
        if candidate_key in seen_candidates:
            continue
        seen_candidates.add(candidate_key)
        same = 1
        adjusted = int(row.total_point)
        for member in source.run_members(table, row.server_time, row.total_point, row.success_user):
            point = int(member.point or 0)
            if point <= 0 or member.char_name == row.char_name:
                continue
            member_clan = source.clan_for_character(member.char_name)
            if member_clan == clan:
                same += 1
            else:
                adjusted -= point
        old = int(source.clan_point(clan))
        if same >= minimum_players and adjusted > old:
            updates.append(SodUpdate(
                clan_name=clan,
                old_point=old,
                new_point=adjusted,
                server_time=row.server_time,
                total_point=row.total_point,
                success_user=row.success_user,
                same_clan_participants=same,
                source_character=row.char_name,
            ))
    return {
        "format": FORMAT,
        "status": "READY",
        "table": table,
        "minimum_players": minimum_players,
        "updates": [dataclasses.asdict(x) for x in updates],
        "write_authorized": False,
        "legacy_corrections": [
            "SQL identifiers are validated and values are parameterized instead of string-concatenated.",
            "Equivalent run/clan candidates are deduplicated before planning updates.",
            "The operation is a dry-run plan until an explicit apply confirmation is supplied.",
        ],
    }


def apply_sod_updates(source: SodDataSource, plan: dict[str, Any], *, confirmation: str) -> dict[str, Any]:
    if confirmation != APPLY_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{APPLY_CONFIRM}")
    applied = []
    for row in plan.get("updates") or []:
        clan = str(row["clan_name"])
        expected = int(row["old_point"])
        current = int(source.clan_point(clan))
        if current != expected:
            raise ValueError(f"CLAN_POINT_DRIFTED:{clan}:{expected}->{current}")
        source.update_clan_point(clan, int(row["new_point"]))
        applied.append({"clan_name": clan, "old_point": current, "new_point": int(row["new_point"])})
    return {"format": FORMAT, "status": "PASS", "applied": applied}


class SQLiteSodDataSource:
    """Local SQLite adapter for the recovered SoD workflow.

    The modern server runs locally and persists its management/game tables in
    SQLite.  Two database files may be supplied when game-record and clan data
    are separated; when ``clan_db`` is omitted the same database is used for
    both.  No network service, ODBC driver or credentials are required.
    """

    def __init__(self, game_db: str | Path, clan_db: str | Path | None = None):
        self.game_path = Path(game_db).expanduser().resolve()
        self.clan_path = Path(clan_db).expanduser().resolve() if clan_db is not None else self.game_path
        self.game = sqlite3.connect(self.game_path)
        self.game.row_factory = sqlite3.Row
        if self.clan_path == self.game_path:
            self.clan = self.game
            self._shared = True
        else:
            self.clan = sqlite3.connect(self.clan_path)
            self.clan.row_factory = sqlite3.Row
            self._shared = False

    def close(self) -> None:
        if not self._shared:
            self.clan.close()
        self.game.close()

    def __enter__(self) -> "SQLiteSodDataSource":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def runs(self, table: str) -> Iterable[SodRow]:
        table = validate_table_name(table)
        sql = f'SELECT CharName, ServerTime, TotalPoint, SuccessUser FROM "{table}"'
        for row in self.game.execute(sql):
            yield SodRow(str(row[0]), int(row[1]), int(row[2]), int(row[3]))

    def run_members(self, table: str, server_time: int, total_point: int, success_user: int) -> Iterable[SodRow]:
        table = validate_table_name(table)
        sql = f'SELECT CharName, Point FROM "{table}" WHERE ServerTime=? AND TotalPoint=? AND SuccessUser=?'
        for row in self.game.execute(sql, (int(server_time), int(total_point), int(success_user))):
            yield SodRow(str(row[0]), int(server_time), int(total_point), int(success_user), int(row[1]))

    def clan_for_character(self, char_name: str) -> str:
        row = self.clan.execute('SELECT ClanName FROM "UL" WHERE ChName=?', (char_name,)).fetchone()
        return str(row[0]) if row else ""

    def clan_point(self, clan_name: str) -> int:
        row = self.clan.execute('SELECT Cpoint FROM "CL" WHERE ClanName=?', (clan_name,)).fetchone()
        return int(row[0]) if row else 0

    def update_clan_point(self, clan_name: str, point: int) -> None:
        self.clan.execute('UPDATE "CL" SET Cpoint=? WHERE ClanName=?', (int(point), clan_name))
        self.clan.commit()

    def top_clan(self) -> str:
        row = self.clan.execute('SELECT ClanName FROM "CL" ORDER BY Cpoint DESC LIMIT 1').fetchone()
        return str(row[0]) if row else ""

    def clan_money(self, clan_name: str) -> int:
        row = self.clan.execute('SELECT ClanMoney FROM "CL" WHERE ClanName=?', (clan_name,)).fetchone()
        return int(row[0]) if row else 0

    def update_clan_money(self, clan_name: str, money: int) -> None:
        self.clan.execute('UPDATE "CL" SET ClanMoney=? WHERE ClanName=?', (int(money), clan_name))
        self.clan.commit()


class PyodbcSodDataSource:
    """Historical SQL Server adapter retained only for migration/reference.

    The active product path uses :class:`SQLiteSodDataSource`; this class is not
    a runtime dependency and should not be exposed by the Fedora UI.


    No credentials are embedded.  The caller supplies two ODBC connection
    strings: one for the SoD/game-record database and one for ClanDB.
    """
    def __init__(self, game_connection_string: str, clan_connection_string: str):
        try:
            import pyodbc  # type: ignore
        except Exception as exc:
            raise RuntimeError("PYODBC_REQUIRED: install pyodbc plus a SQL Server ODBC driver") from exc
        self._pyodbc = pyodbc
        self.game = pyodbc.connect(game_connection_string)
        self.clan = pyodbc.connect(clan_connection_string)

    def close(self) -> None:
        self.game.close(); self.clan.close()

    def runs(self, table: str) -> Iterable[SodRow]:
        table = validate_table_name(table)
        cur = self.game.cursor()
        for row in cur.execute(f"SELECT CharName, ServerTime, TotalPoint, SuccessUser FROM [{table}]"):
            yield SodRow(str(row[0]), int(row[1]), int(row[2]), int(row[3]))

    def run_members(self, table: str, server_time: int, total_point: int, success_user: int) -> Iterable[SodRow]:
        table = validate_table_name(table)
        cur = self.game.cursor()
        sql = f"SELECT CharName, Point FROM [{table}] WHERE ServerTime=? AND TotalPoint=? AND SuccessUser=?"
        for row in cur.execute(sql, server_time, total_point, success_user):
            yield SodRow(str(row[0]), server_time, total_point, success_user, int(row[1]))

    def clan_for_character(self, char_name: str) -> str:
        row = self.clan.cursor().execute("SELECT ClanName FROM UL WHERE ChName=?", char_name).fetchone()
        return str(row[0]) if row else ""

    def clan_point(self, clan_name: str) -> int:
        row = self.clan.cursor().execute("SELECT Cpoint FROM CL WHERE ClanName=?", clan_name).fetchone()
        return int(row[0]) if row else 0

    def update_clan_point(self, clan_name: str, point: int) -> None:
        cur = self.clan.cursor(); cur.execute("UPDATE CL SET Cpoint=? WHERE ClanName=?", int(point), clan_name); self.clan.commit()

    def top_clan(self) -> str:
        row = self.clan.cursor().execute("SELECT TOP 1 ClanName FROM CL ORDER BY Cpoint DESC").fetchone()
        return str(row[0]) if row else ""

    def clan_money(self, clan_name: str) -> int:
        row = self.clan.cursor().execute("SELECT ClanMoney FROM CL WHERE ClanName=?", clan_name).fetchone()
        return int(row[0]) if row else 0

    def update_clan_money(self, clan_name: str, money: int) -> None:
        cur = self.clan.cursor(); cur.execute("UPDATE CL SET ClanMoney=? WHERE ClanName=?", int(money), clan_name); self.clan.commit()
