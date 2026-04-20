"""Display-data projection of buildings and belts.

A pure, read-only layer that turns simulation objects (``Miner``,
``Assembler``, ``ConveyorBelt``) into the rows and bars the tooltip and
selected-structure menu render. Centralising the ipm math here keeps the
two UIs pixel-consistent and gives tests a single target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..belts.belt import ConveyorBelt
from ..buildings.assembler import Assembler
from ..buildings.building import Building
from ..buildings.miner import Miner
from ..buildings.port import Port, PortKind
from ..core import config
from ..items.item_type import ItemType
from ..world.direction import Direction
from ..world.tile import Coord

if TYPE_CHECKING:
    from ..belts.network_soa import BeltNetworkSoA
    from ..world.world import World


_DIR_NAME: dict[Direction, str] = {
    Direction.N: "North",
    Direction.E: "East",
    Direction.S: "South",
    Direction.W: "West",
}


def miner_ipm(period_ticks: int) -> float:
    """Nominal miner output in items/minute at ``TICK_HZ``."""
    period_ticks = max(1, int(period_ticks))
    return (60.0 * config.TICK_HZ) / period_ticks


def assembler_cycles_per_minute(recipe_ticks: int) -> float:
    recipe_ticks = max(1, int(recipe_ticks))
    return (60.0 * config.TICK_HZ) / recipe_ticks


def belt_max_ipm() -> float:
    """Theoretical max items/minute per belt lane (1 slot/tick advancement)."""
    return 60.0 * config.TICK_HZ


def _fmt_rate(v: float) -> str:
    # Collapse integer-valued rates (60.0 -> "60") so numbers read clean.
    if abs(v - round(v)) < 1e-6:
        return f"{int(round(v))}/min"
    if v >= 10:
        return f"{v:.1f}/min"
    return f"{v:.2f}/min"


@dataclass(frozen=True)
class PortInfo:
    """Projection of a ``Port`` for UI rendering."""

    kind: PortKind
    side: Direction
    item: ItemType | None
    count: int
    capacity: int
    cell_offset: Coord = (0, 0)
    index: int = 0

    @property
    def fill(self) -> float:
        if self.capacity <= 0:
            return 0.0
        return max(0.0, min(1.0, self.count / self.capacity))

    @property
    def is_full(self) -> bool:
        return self.count >= self.capacity and self.capacity > 0


@dataclass(frozen=True)
class InfoRow:
    """One key/value row (optionally coloured by an item)."""

    label: str
    value: str
    item: ItemType | None = None
    accent: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class StructureInfo:
    """Everything the tooltip + side menu need about a structure."""

    kind: str                 # "miner" | "assembler" | "belt"
    title: str
    subtitle: str
    accent: tuple[int, int, int]
    primary_item: ItemType | None = None
    footprint: tuple[int, int] = (1, 1)
    rotation: Direction = Direction.E
    mirrored: bool = False
    rate_rows: tuple[InfoRow, ...] = ()
    port_rows: tuple[PortInfo, ...] = ()
    progress: float | None = None
    progress_label: str | None = None
    tooltip_rows: tuple[InfoRow, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _port_info(
    port: Port,
    *,
    origin: Coord,
    index: int,
    fallback_item: ItemType | None = None,
) -> PortInfo:
    item = port.filter if port.filter is not None else fallback_item
    ox, oy = origin
    cx, cy = port.cell
    return PortInfo(
        kind=port.kind,
        side=port.side,
        item=item,
        count=int(port.count),
        capacity=int(port.capacity),
        cell_offset=(cx - ox, cy - oy),
        index=index,
    )


def _direction_word(d: Direction) -> str:
    return _DIR_NAME.get(d, str(d.name))


def _enumerate_ports(
    origin: Coord,
    inputs: tuple[Port, ...] | list[Port],
    outputs: tuple[Port, ...] | list[Port],
    *,
    fallback_item: ItemType | None = None,
) -> tuple[PortInfo, ...]:
    rows: list[PortInfo] = []
    idx = 0
    for p in inputs:
        rows.append(_port_info(p, origin=origin, index=idx, fallback_item=fallback_item))
        idx += 1
    for p in outputs:
        rows.append(_port_info(p, origin=origin, index=idx, fallback_item=fallback_item))
        idx += 1
    return tuple(rows)


def for_miner(m: Miner, world: World | None = None) -> StructureInfo:
    effective_period = m.effective_period_ticks(world)
    rate = miner_ipm(effective_period)
    title = f"{m.item.name} Miner"
    subtitle = f"Miner - facing {_direction_word(m.rotation)}"
    if m.mirrored:
        subtitle += " (mirrored)"
    cycle_label = f"{effective_period} ticks"
    if effective_period != m.period_ticks:
        cycle_label = f"{effective_period} ticks (base {m.period_ticks})"
    rate_rows = (
        InfoRow(label="Output", value=_fmt_rate(rate), item=m.item),
        InfoRow(label="Cycle", value=cycle_label),
    )
    # Miner output ports are unfiltered -- surface the mined item so the
    # port bar in the menu can still colour it correctly.
    port_rows = _enumerate_ports(
        m.origin, m.inputs, m.outputs, fallback_item=m.item
    )
    tooltip_rows = (
        InfoRow(label="Produces", value=m.item.name, item=m.item),
        InfoRow(label="Rate", value=_fmt_rate(rate), item=m.item),
    )
    return StructureInfo(
        kind="miner",
        title=title,
        subtitle=subtitle,
        accent=m.item.color,
        primary_item=m.item,
        footprint=m.footprint,
        rotation=m.rotation,
        mirrored=m.mirrored,
        rate_rows=rate_rows,
        port_rows=port_rows,
        progress=None,
        progress_label=None,
        tooltip_rows=tooltip_rows,
    )


def for_assembler(a: Assembler, world: World | None = None) -> StructureInfo:
    effective_ticks = a.effective_recipe_ticks(world)
    cpm = assembler_cycles_per_minute(effective_ticks)
    primary_out = a.recipe.outputs[0][0] if a.recipe.outputs else None
    title = f"{primary_out.name} Assembler" if primary_out is not None else "Assembler"
    subtitle = f"Assembler - facing {_direction_word(a.rotation)}"
    if a.mirrored:
        subtitle += " (mirrored)"

    rate_rows: list[InfoRow] = []
    for item, qty in a.recipe.inputs:
        rate_rows.append(
            InfoRow(
                label=f"In - {item.name}",
                value=f"{qty}x  {_fmt_rate(cpm * qty)}",
                item=item,
            )
        )
    for item, qty in a.recipe.outputs:
        rate_rows.append(
            InfoRow(
                label=f"Out - {item.name}",
                value=f"{qty}x  {_fmt_rate(cpm * qty)}",
                item=item,
            )
        )

    port_rows = _enumerate_ports(a.origin, a.inputs, a.outputs)

    if a.is_crafting:
        done, total = a.craft_ticks
        progress: float | None = a.craft_progress
        progress_label = (
            f"Crafting {primary_out.name if primary_out else 'item'}  {done}/{total}"
        )
    else:
        progress = 0.0 if primary_out is not None else None
        progress_label = "Waiting for inputs" if primary_out is not None else None

    tooltip_rows: list[InfoRow] = []
    if primary_out is not None:
        tooltip_rows.append(
            InfoRow(label="Produces", value=primary_out.name, item=primary_out)
        )
        tooltip_rows.append(
            InfoRow(
                label="Rate",
                value=_fmt_rate(cpm * a.recipe.outputs[0][1]),
                item=primary_out,
            )
        )
    if a.is_crafting:
        tooltip_rows.append(
            InfoRow(label="Progress", value=f"{int((progress or 0.0) * 100)}%")
        )

    return StructureInfo(
        kind="assembler",
        title=title,
        subtitle=subtitle,
        accent=(primary_out.color if primary_out is not None else (245, 165, 36)),
        primary_item=primary_out,
        footprint=a.footprint,
        rotation=a.rotation,
        mirrored=a.mirrored,
        rate_rows=tuple(rate_rows),
        port_rows=port_rows,
        progress=progress,
        progress_label=progress_label,
        tooltip_rows=tuple(tooltip_rows),
    )


def for_belt(b: ConveyorBelt, net: BeltNetworkSoA | None) -> StructureInfo:
    max_rate = belt_max_ipm()
    title = "Conveyor Belt"
    subtitle = f"Belt - flowing {_direction_word(b.direction)}"

    rate_rows: list[InfoRow] = [
        InfoRow(label="Max flow", value=_fmt_rate(max_rate)),
        InfoRow(label="Slots", value=f"{ConveyorBelt.SLOTS} / tile"),
    ]
    chain_index: int | None = None
    if net is not None and b.chain_index >= 0:
        chain_index = int(b.chain_index)
        occupancy = net.item_count_at(b.pos)
        rate_rows.append(
            InfoRow(label="Load", value=f"{occupancy}/{ConveyorBelt.SLOTS}")
        )

    tooltip_rows: tuple[InfoRow, ...] = (
        InfoRow(label="Direction", value=_direction_word(b.direction)),
        InfoRow(label="Max flow", value=_fmt_rate(max_rate)),
    )
    if chain_index is not None and net is not None:
        tooltip_rows = tooltip_rows + (
            InfoRow(label="Chain", value=f"#{chain_index}"),
        )

    return StructureInfo(
        kind="belt",
        title=title,
        subtitle=subtitle,
        accent=(77, 163, 255),  # PALETTE.secondary
        primary_item=None,
        footprint=(1, 1),
        rotation=b.direction,
        rate_rows=tuple(rate_rows),
        port_rows=(),
        progress=None,
        progress_label=None,
        tooltip_rows=tooltip_rows,
    )


def for_building(b: Building, world: World | None = None) -> StructureInfo | None:
    if isinstance(b, Miner):
        return for_miner(b, world)
    if isinstance(b, Assembler):
        return for_assembler(b, world)
    return None


def brief(info: StructureInfo) -> tuple[InfoRow, ...]:
    """Short row list for the hover tooltip."""
    return info.tooltip_rows
