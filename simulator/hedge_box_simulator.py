from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class HedgeBoxInputs:
    dte: int
    spot: float
    ce_short: int
    pe_short: int
    ce_break_even: int | None
    pe_break_even: int | None
    box_width: int = 75
    strike_step: int = 50
    ato_ce_engaged: bool = False
    ato_pe_engaged: bool = False


@dataclass(frozen=True)
class SideDecision:
    side: str
    state: str
    action: str
    strike: int | None


@dataclass(frozen=True)
class ScenarioDecision:
    spot: float
    ce_state: str
    pe_state: str
    ce_action: str
    pe_action: str
    ce_strike: int | None
    pe_strike: int | None
    summary: str


@dataclass(frozen=True)
class ProfileDefaults:
    dte: int
    ce_short: int
    pe_short: int
    ce_be: int
    pe_be: int
    box_width: int
    strike_step: int
    spots: tuple[float, ...]


PROFILES: dict[str, ProfileDefaults] = {
    "core_22apr": ProfileDefaults(
        dte=3,
        ce_short=24750,
        pe_short=24150,
        ce_be=24993,
        pe_be=23907,
        box_width=75,
        strike_step=50,
        spots=(24810, 24760, 24749, 24690, 24650, 24601, 24550, 24290, 24210, 24140),
    )
}


def round_to_strike(value: float, step: int = 50) -> int:
    if step != 50:
        lower = int(value // step) * step
        upper = lower + step
        if value - lower < upper - value:
            return lower
        return upper

    # User-locked rounding for 50-step strikes:
    # [xx00, xx25) -> xx00
    # [xx25, xx75) -> xx50
    # [xx75, xx100) -> next xx00
    base_100 = int(value // 100) * 100
    offset = value - base_100

    if offset < 25:
        return base_100
    if offset < 75:
        return base_100 + 50
    return base_100 + 100


def active_bands_for_dte(dte: int) -> int:
    if dte >= 4:
        return 1
    if dte == 3:
        return 2
    if dte == 2:
        return 3
    if dte == 1:
        return 4
    return 0


def color_order_for_dte(dte: int) -> list[str]:
    """Return active color order from short-strike edge toward center."""
    if dte >= 4:
        return ["Green"]
    if dte == 3:
        return ["Orange", "Green"]
    if dte == 2:
        return ["Blue", "Orange", "Green"]
    if dte == 1:
        return ["Yellow", "Blue", "Orange", "Green"]
    return []


def classify_side_state(side: str, spot: float, short_strike: int, box_width: int, dte: int) -> str:
    if side == "CE":
        if spot >= short_strike:
            return "Breach"
        active_colors = color_order_for_dte(dte)
        for i, color in enumerate(active_colors):
            upper = short_strike - i * box_width
            lower = short_strike - (i + 1) * box_width
            if lower <= spot < upper:
                return color
        return "White"

    if side == "PE":
        if spot <= short_strike:
            return "Breach"
        active_colors = color_order_for_dte(dte)
        for i, color in enumerate(active_colors):
            lower = short_strike + i * box_width
            upper = short_strike + (i + 1) * box_width
            if lower < spot <= upper:
                return color
        return "White"

    raise ValueError(f"Unsupported side: {side}")


def inside_steps_for_state(state: str) -> int | None:
    mapping = {
        "Orange": 2,
        "Green": 1,
        "Blue": 3,
        "Yellow": 4,
    }
    return mapping.get(state)


def decide_side(side: str, state: str, inp: HedgeBoxInputs) -> SideDecision:
    side_break_even = inp.ce_break_even if side == "CE" else inp.pe_break_even

    # Side-level boundary: if break-even is missing/skipped for this side,
    # Hedge Box must not place new hedges for this side.
    if side_break_even is None:
        if side == "CE" and state == "Breach" and inp.ato_ce_engaged:
            return SideDecision(side, state, "keep_engaged_ato", None)
        if side == "PE" and state == "Breach" and inp.ato_pe_engaged:
            return SideDecision(side, state, "keep_engaged_ato", None)
        return SideDecision(side, state, "skip_missing_break_even", None)

    if side == "CE":
        if state == "Breach":
            if inp.ato_ce_engaged:
                return SideDecision(side, state, "keep_engaged_ato", None)
            return SideDecision(side, state, "breach_protect", inp.ce_short + inp.strike_step)

        steps = inside_steps_for_state(state)
        if steps is None:
            return SideDecision(
                side,
                state,
                "standard_break_even",
                round_to_strike(inp.ce_break_even, inp.strike_step),
            )

        raw = inp.ce_break_even - (steps * inp.strike_step)
        target = round_to_strike(raw, inp.strike_step)
        floor_guardrail = inp.ce_short + inp.strike_step
        target = max(target, floor_guardrail)
        return SideDecision(side, state, f"{state.lower()}_inside", target)

    if side == "PE":
        if state == "Breach":
            if inp.ato_pe_engaged:
                return SideDecision(side, state, "keep_engaged_ato", None)
            return SideDecision(side, state, "breach_protect", inp.pe_short - inp.strike_step)

        steps = inside_steps_for_state(state)
        if steps is None:
            return SideDecision(
                side,
                state,
                "standard_break_even",
                round_to_strike(inp.pe_break_even, inp.strike_step),
            )

        raw = inp.pe_break_even + (steps * inp.strike_step)
        target = round_to_strike(raw, inp.strike_step)
        ceiling_guardrail = inp.pe_short - inp.strike_step
        target = min(target, ceiling_guardrail)
        return SideDecision(side, state, f"{state.lower()}_inside", target)

    raise ValueError(f"Unsupported side: {side}")


def simulate_one(inp: HedgeBoxInputs) -> ScenarioDecision:
    # 0DTE boundary: no Hedge Box actions on expiry day.
    if inp.dte == 0:
        return ScenarioDecision(
            spot=inp.spot,
            ce_state="NoAction",
            pe_state="NoAction",
            ce_action="skip_0dte",
            pe_action="skip_0dte",
            ce_strike=None,
            pe_strike=None,
            summary="0DTE: Hedge Box execution skipped on both sides",
        )

    ce_state = classify_side_state("CE", inp.spot, inp.ce_short, inp.box_width, inp.dte)
    pe_state = classify_side_state("PE", inp.spot, inp.pe_short, inp.box_width, inp.dte)

    ce_decision = decide_side("CE", ce_state, inp)
    pe_decision = decide_side("PE", pe_state, inp)

    summary = (
        f"CE {ce_decision.action}"
        + (f" @ {ce_decision.strike}" if ce_decision.strike is not None else "")
        + " | "
        + f"PE {pe_decision.action}"
        + (f" @ {pe_decision.strike}" if pe_decision.strike is not None else "")
    )

    return ScenarioDecision(
        spot=inp.spot,
        ce_state=ce_state,
        pe_state=pe_state,
        ce_action=ce_decision.action,
        pe_action=pe_decision.action,
        ce_strike=ce_decision.strike,
        pe_strike=pe_decision.strike,
        summary=summary,
    )


def render_markdown_table(rows: Iterable[ScenarioDecision]) -> str:
    lines = [
        "| Spot | CE State | PE State | CE Action | PE Action | CE Strike | PE Strike | Summary |",
        "|---:|---|---|---|---|---:|---:|---|",
    ]
    for row in rows:
        ce_strike = "-" if row.ce_strike is None else str(row.ce_strike)
        pe_strike = "-" if row.pe_strike is None else str(row.pe_strike)
        lines.append(
            "| "
            + f"{row.spot:.2f} | {row.ce_state} | {row.pe_state} | {row.ce_action} | "
            + f"{row.pe_action} | {ce_strike} | {pe_strike} | {row.summary} |"
        )
    return "\n".join(lines)


def _safe_int(value: int | None) -> str:
    return "" if value is None else str(value)


def build_matrix_rows(
    *,
    ce_short: int,
    pe_short: int,
    ce_be: int | None,
    pe_be: int | None,
    box_width: int,
    strike_step: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    dte_map = [(4, "Wednesday"), (3, "Thursday"), (2, "Friday"), (1, "Monday"), (0, "Tuesday")]

    def side_params(side: str) -> tuple[int, int | None]:
        if side == "CE":
            return ce_short, ce_be
        return pe_short, pe_be

    for dte, day_name in dte_map:
        active_colors = color_order_for_dte(dte)
        for side in ("CE", "PE"):
            if dte == 0:
                rows.append(
                    {
                        "day": day_name,
                        "dte": str(dte),
                        "side": side,
                        "zone": "NoAction",
                        "range_start": "",
                        "range_end": "",
                        "hedge_strike": "",
                    }
                )
                continue

            short_strike, be_value = side_params(side)

            # Standard hedge row (White-zone behavior)
            if dte == 0:
                # 0DTE boundary: Tuesday has no Hedge Box hedge buys.
                standard_strike = None
            elif be_value is None:
                standard_strike = None
            else:
                standard_strike = round_to_strike(be_value, strike_step)

            rows.append(
                {
                    "day": day_name,
                    "dte": str(dte),
                    "side": side,
                    "zone": "White",
                    "range_start": "",
                    "range_end": "",
                    "hedge_strike": _safe_int(standard_strike),
                }
            )

            # Color-zone rows
            for i, color in enumerate(active_colors):
                if side == "CE":
                    range_start = short_strike - (i + 1) * box_width
                    range_end = short_strike - i * box_width
                else:
                    range_start = short_strike + i * box_width
                    range_end = short_strike + (i + 1) * box_width

                if be_value is None:
                    strike = None
                else:
                    steps = inside_steps_for_state(color)
                    assert steps is not None
                    if side == "CE":
                        raw = be_value - (steps * strike_step)
                        strike = round_to_strike(raw, strike_step)
                        strike = max(strike, short_strike + strike_step)
                    else:
                        raw = be_value + (steps * strike_step)
                        strike = round_to_strike(raw, strike_step)
                        strike = min(strike, short_strike - strike_step)

                rows.append(
                    {
                        "day": day_name,
                        "dte": str(dte),
                        "side": side,
                        "zone": color,
                        "range_start": str(range_start),
                        "range_end": str(range_end),
                        "hedge_strike": _safe_int(strike),
                    }
                )

    return rows


def export_matrix_csv(
    *,
    ce_short: int,
    pe_short: int,
    ce_be: int | None,
    pe_be: int | None,
    box_width: int,
    strike_step: int,
    output_path: Path,
) -> Path:
    rows = build_matrix_rows(
        ce_short=ce_short,
        pe_short=pe_short,
        ce_be=ce_be,
        pe_be=pe_be,
        box_width=box_width,
        strike_step=strike_step,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "day",
                "dte",
                "side",
                "zone",
                "range_start",
                "range_end",
                "hedge_strike",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    return output_path


def apply_profile_defaults(args: argparse.Namespace) -> None:
    if args.profile is None:
        return

    profile = PROFILES[args.profile]
    if args.dte is None:
        args.dte = profile.dte
    if args.ce_short is None:
        args.ce_short = profile.ce_short
    if args.pe_short is None:
        args.pe_short = profile.pe_short
    if args.ce_be is None:
        args.ce_be = profile.ce_be
    if args.pe_be is None:
        args.pe_be = profile.pe_be
    if args.box_width is None:
        args.box_width = profile.box_width
    if args.strike_step is None:
        args.strike_step = profile.strike_step
    if args.spots is None:
        args.spots = list(profile.spots)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hedge Box scenario simulator")
    parser.add_argument("--profile", choices=sorted(PROFILES.keys()))
    parser.add_argument("--dte", type=int, help="Working-days-to-expiry")
    parser.add_argument("--spots", type=float, nargs="+", help="Spot values")
    parser.add_argument("--ce-short", type=int)
    parser.add_argument("--pe-short", type=int)
    parser.add_argument("--ce-be", type=int, help="CE break-even from image")
    parser.add_argument("--pe-be", type=int, help="PE break-even from image")
    parser.add_argument("--ce-be-missing", action="store_true")
    parser.add_argument("--pe-be-missing", action="store_true")
    parser.add_argument("--box-width", type=int)
    parser.add_argument("--strike-step", type=int)
    parser.add_argument("--export-matrix", action="store_true")
    parser.add_argument("--matrix-output", type=str)
    parser.add_argument("--ato-ce-engaged", action="store_true")
    parser.add_argument("--ato-pe-engaged", action="store_true")
    args = parser.parse_args()

    apply_profile_defaults(args)

    if args.ce_be_missing:
        args.ce_be = None
    if args.pe_be_missing:
        args.pe_be = None

    missing: list[str] = []
    if args.dte is None:
        missing.append("--dte")
    if args.spots is None:
        missing.append("--spots")
    if args.ce_short is None:
        missing.append("--ce-short")
    if args.pe_short is None:
        missing.append("--pe-short")
    if args.ce_be is None and not args.ce_be_missing:
        missing.append("--ce-be")
    if args.pe_be is None and not args.pe_be_missing:
        missing.append("--pe-be")
    if args.box_width is None:
        missing.append("--box-width")
    if args.strike_step is None:
        missing.append("--strike-step")

    if missing:
        parser.error(
            "missing required args: "
            + ", ".join(missing)
            + ". "
            + "Use --profile core_22apr for quick defaults."
        )

    return args


def main() -> None:
    args = parse_args()

    if args.export_matrix:
        if args.matrix_output is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            matrix_path = Path(f"data/analytics/hedge_box/hedge_box_matrix_{stamp}.csv")
        else:
            matrix_path = Path(args.matrix_output)

        out = export_matrix_csv(
            ce_short=args.ce_short,
            pe_short=args.pe_short,
            ce_be=args.ce_be,
            pe_be=args.pe_be,
            box_width=args.box_width,
            strike_step=args.strike_step,
            output_path=matrix_path,
        )
        print(f"MATRIX_EXPORTED: {out}")

    rows: list[ScenarioDecision] = []

    for spot in args.spots:
        inp = HedgeBoxInputs(
            dte=args.dte,
            spot=spot,
            ce_short=args.ce_short,
            pe_short=args.pe_short,
            ce_break_even=args.ce_be,
            pe_break_even=args.pe_be,
            box_width=args.box_width,
            strike_step=args.strike_step,
            ato_ce_engaged=args.ato_ce_engaged,
            ato_pe_engaged=args.ato_pe_engaged,
        )
        rows.append(simulate_one(inp))

    print(render_markdown_table(rows))


if __name__ == "__main__":
    main()
