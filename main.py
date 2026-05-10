"""Sweet Works entry point."""

from __future__ import annotations

from src.core.game import Game
from src.scenes.menu_scene import MenuScene


def main() -> None:
    game = Game()
    game.push_scene(MenuScene())
    game.run()


if __name__ == "__main__":
    main()
