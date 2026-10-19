"""隔離表的分類（reject_category 欄）：全專案唯一一份定義。

fact_order（格式、撞號、重複、匯率、品質規則）與 order_status_check（狀態機）共用。
每列訂單恰好落在一個分類，或寫進 fact；三種去向互斥，相加等於輸入：

- 寫進 fact：不在隔離表。
- 隔離（QUARANTINE_CATEGORIES）：在隔離表，需要人看。
- 略過（SKIP_CATEGORIES）：也存在隔離表（使用者定：狀況外的事件統一留紀錄），
  但不是錯誤，對帳時和「隔離」分開計數。
"""

from __future__ import annotations


class Category:
    """reject_category 的值，各類別互斥。"""

    # ---- fact_order
    CONTRACT = "contract"  # cast_to_contract 的列層級違規（含值不在允許範圍）
    COLLISION = "collision"  # 同批同 order_id、不可變欄位不同，整組隔離
    DUPLICATE = "duplicate"  # 與保留的那列除 updated_at 外全同（V7）
    COLLISION_EXISTING = "collision_existing"  # 與既有 fact 撞號
    FX_MISSING = "fx_missing"  # 下單日找不到匯率
    QUALITY = "quality"  # A-3 品質規則（目前沒有規則）
    # ---- 狀態機（order_status_check）
    SUPERSEDED = "superseded"  # 合法，但同批有較新的合法事件
    LATE_EVENT = "late_event"  # 晚到、走得到 fact 現況：略過
    LATE_EVENT_CONFLICT = "late_event_conflict"  # 晚到、走不到 fact 現況
    ILLEGAL_TRANSITION = "illegal_transition"  # 往回走
    AFTER_ILLEGAL = "after_illegal"  # 同批較早的事件不合法或無法排序，之後的一起隔離
    AMBIGUOUS_ORDER = "ambiguous_order"  # 同一 order_id 同一秒不同狀態


SKIP_CATEGORIES: frozenset[str] = frozenset({Category.LATE_EVENT})

QUARANTINE_CATEGORIES: frozenset[str] = frozenset(
    v
    for k, v in vars(Category).items()
    if not k.startswith("_") and isinstance(v, str) and v not in SKIP_CATEGORIES
)
