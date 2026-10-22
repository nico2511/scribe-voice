"""Faux ``winsound`` : pas de bip pendant les tests."""


def Beep(freq, ms):
    return None
