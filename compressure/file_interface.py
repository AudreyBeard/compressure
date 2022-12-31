import re


# https://stackoverflow.com/questions/4623446/how-do-you-sort-files-numerically
def tryint(s: str):
    try:
        return int(s)
    except ValueError:
        return s


def alphanum_key(s: str):
    """ Turn a string into a list of string and number chunks.
        "z23a" -> ["z", 23, "a"]
    """
    return [tryint(c) for c in re.split('([0-9]+)', s)]


def sort_nicely(strings: list) -> list:
    """ Sort the given list in the way that humans expect.
    """
    strings.sort(key=alphanum_key)


def nicely_sorted(strings: list) -> list:
    """ Analog for sorted function for intuitive sorting
    """
    sort_nicely(strings)
    return strings
