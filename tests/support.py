from contextlib import closing


def player(store, user="u1"):
    with closing(store.connect()) as conn:
        return dict(conn.execute("SELECT * FROM players WHERE user_id=?", (user,)).fetchone())


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
