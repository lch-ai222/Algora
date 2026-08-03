"""Core domain records. Kept dependency-free so every other module can import it."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: float  # unit price in dollars
    category: str = "general"


@dataclass
class CartItem:
    product: Product
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass
class Order:
    order_id: str
    items: list[CartItem] = field(default_factory=list)
    subtotal: float = 0.0
    discount: float = 0.0
    tax: float = 0.0
    total: float = 0.0
    tax_rate: float = 0.08


@dataclass(frozen=True)
class ReturnItem:
    sku: str
    quantity: int
    net_refund: float


@dataclass(frozen=True)
class ReturnReceipt:
    order_id: str
    items: tuple[ReturnItem, ...]
    subtotal_refund: float
    tax_refund: float
    total_refund: float
    points_reversed: int
