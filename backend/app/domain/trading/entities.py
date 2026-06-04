from dataclasses import dataclass


@dataclass
class OrderInfo:
    order_number: int
    price: float
    size: float
