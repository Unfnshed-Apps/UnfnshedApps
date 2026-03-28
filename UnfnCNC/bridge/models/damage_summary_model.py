"""
QAbstractListModel for the damage summary table in the damage dialog.
"""

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex


class DamageSummaryModel(QAbstractListModel):
    NameRole = Qt.UserRole + 1
    QuantityRole = Qt.UserRole + 2
    DamagedRole = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []  # list of dicts: {name, quantity, damaged}

    def roleNames(self):
        return {
            self.NameRole: b"name",
            self.QuantityRole: b"quantity",
            self.DamagedRole: b"damaged",
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.NameRole:
            return item["name"]
        if role == self.QuantityRole:
            return item["quantity"]
        if role == self.DamagedRole:
            return item["damaged"]
        return None

    def resetFromInstances(self, part_instances):
        """Aggregate damage summary from part_instances list."""
        summary = {}
        for part in part_instances:
            name = part.component_name
            if part.ambiguous_group is not None and not name:
                name = f"Unknown (group {part.ambiguous_group})"
            if not name:
                name = f"Part {part.instance_id}"
            if name not in summary:
                summary[name] = {"qty": 0, "damaged": 0}
            summary[name]["qty"] += 1
            if part.is_damaged:
                summary[name]["damaged"] += 1

        self.beginResetModel()
        self._items = [
            {"name": name, "quantity": data["qty"], "damaged": data["damaged"]}
            for name, data in summary.items()
        ]
        self.endResetModel()
