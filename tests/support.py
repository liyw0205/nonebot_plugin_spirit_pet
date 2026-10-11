from contextlib import closing


def player(store, user="u1"):
    with closing(store.connect()) as conn:
        return dict(conn.execute("SELECT * FROM players WHERE user_id=?", (user,)).fetchone())


def player_uid(store, user="u1"):
    with closing(store.connect()) as conn:
        row = conn.execute("SELECT id FROM player_identity WHERE user_id=?", (user,)).fetchone()
        return int(row["id"]) + 9999


def uid_label(store, user="u1"):
    return f"UID {player_uid(store, user)}"


def pet(store, user="u1"):
    with closing(store.connect()) as conn:
        return dict(conn.execute(
            "SELECT t.* FROM pets t JOIN players p ON p.active_pet_id=t.pet_id WHERE p.user_id=?", (user,),
        ).fetchone())


def items(store, user="u1"):
    with closing(store.connect()) as conn:
        return dict(conn.execute("SELECT item_id, quantity FROM inventory WHERE user_id=?", (user,)))


def sql(store, statement, args=()):
    with closing(store.connect()) as conn:
        return [dict(row) for row in conn.execute(statement, args)]
