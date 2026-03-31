"""Pure game logic — no IO, no side effects. Operates on list[Cell]."""
from models import Cell, Coord, GameStatus, Player

DIRECTIONS = [(1, 0), (0, 1), (1, -1)]


def hex_distance(q1: int, r1: int, q2: int, r2: int) -> int:
    return max(abs(q1 - q2), abs(r1 - r2), abs((-q1 - r1) - (-q2 - r2)))


def valid_placement_cells(cells: list[Cell], view_distance: int) -> list[Coord]:
    occupied = {(c.q, c.r) for c in cells}
    if not occupied:
        return [Coord(q=0, r=0)]
    candidates: set[tuple[int, int]] = set()
    for oq, or_ in occupied:
        for dq in range(-view_distance, view_distance + 1):
            for dr in range(-view_distance, view_distance + 1):
                if hex_distance(0, 0, dq, dr) <= view_distance:
                    nq, nr = oq + dq, or_ + dr
                    if (nq, nr) not in occupied:
                        candidates.add((nq, nr))
    return [Coord(q=q, r=r) for q, r in candidates]


def is_valid_placement(
    cells: list[Cell], coord: Coord, view_distance: int
) -> tuple[bool, str]:
    occupied = {(c.q, c.r) for c in cells}
    if (coord.q, coord.r) in occupied:
        return False, f"({coord.q},{coord.r}) already occupied"
    valid = {(c.q, c.r) for c in valid_placement_cells(cells, view_distance)}
    if (coord.q, coord.r) not in valid:
        return False, f"({coord.q},{coord.r}) out of view range"
    return True, ""


def place_piece(cells: list[Cell], coord: Coord, player: Player) -> list[Cell]:
    return cells + [Cell(q=coord.q, r=coord.r, p=player)]


def check_win(cells: list[Cell], player: Player, win_distance: int) -> bool:
    owned = {(c.q, c.r) for c in cells if c.p == player}
    for q, r in owned:
        for dq, dr in DIRECTIONS:
            length, nq, nr = 1, q + dq, r + dr
            while (nq, nr) in owned:
                length += 1
                if length >= win_distance:
                    return True
                nq += dq
                nr += dr
    return False


def evaluate_status(cells: list[Cell], win_distance: int) -> GameStatus:
    if check_win(cells, Player.X, win_distance):
        return GameStatus.X_WINS
    if check_win(cells, Player.O, win_distance):
        return GameStatus.O_WINS
    return GameStatus.IN_PROGRESS