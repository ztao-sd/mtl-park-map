from typing import TypeVar

T = TypeVar("T", bound=int | float)


def is_within_interval(child: tuple[T, T], parent: tuple[T, T], base: T) -> bool:
    start_, end_ = child
    start, end = parent
    if end < start:
        end += base
        if end_ < start_:
            end_ += base
        else:
            if start_ < start:
                start_ += base
            if end_ < start:
                end_ += base
    else:
        if end_ < start_:
            end_ += base
    return start_ >= start and end_ <= end