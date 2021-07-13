from cp import CommandProcessor
from version import __version__

__all__ = ('CommandProcessor')


if __name__ == "__main__":
    the_cp = CommandProcessor()
    the_cp.run()