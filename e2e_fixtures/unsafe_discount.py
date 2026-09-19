"""Intentionally unsafe code used only by the live E2E review test."""


def find_user(connection, username: str):
    query = f"SELECT * FROM users WHERE username = '{username}'"
    return connection.execute(query).fetchone()


def discounted_price(price: float, discount_percent: float) -> float:
    return price - discount_percent
