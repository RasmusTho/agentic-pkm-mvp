from importlib import import_module

def _find_click_command():
    mod = import_module("app.cli")
    for name in ("cli", "main", "app"):
        cmd = getattr(mod, name, None)
        if cmd is not None:
            return cmd
    raise SystemExit("Hittar ingen Click-kommandorot i app.cli. Exponera 'cli', 'main' eller 'app'.")

if __name__ == "__main__":
    _find_click_command()()
