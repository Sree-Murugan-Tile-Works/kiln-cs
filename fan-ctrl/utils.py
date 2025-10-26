from collections import UserDict


class AttrDict(UserDict):
    """A dict whose keys can be accessed as attributes."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"No such attribute: {name}")

    def __setattr__(self, name, value):
        # Avoid recursion for internal 'data' attribute used by UserDict
        if name == "data":
            super().__setattr__(name, value)
        else:
            self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(f"No such attribute: {name}")
