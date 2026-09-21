"""列表结果集快照.

监测记录增长很快, 传统的 LIMIT/OFFSET 分页在翻页过程中遇到他人新增或删除
记录时会整页位移: 已经看过的记录重复出现、或被挤出窗口而漏掉。

查询页在第一页把当前筛选+排序下的结果集 ID 顺序物化到快照中, 之后翻页
只按快照内的固定位置取数, 与线上表的后续写入完全隔离。汇总数字在创建
快照时计算并固化, 导出也遍历同一份快照, 因此「页头汇总 = 实际导出行数」。
"""
import secrets
from datetime import datetime, timedelta

from ..extensions import db
from .base import iso


class QuerySnapshot(db.Model):
    __tablename__ = "query_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(40), unique=True, nullable=False, index=True)
    # 归一化筛选条件的签名, 防止 token 被复用到不同条件的查询上
    signature = db.Column(db.String(64), nullable=False)
    sort = db.Column(db.String(32), nullable=False)
    order = db.Column(db.String(8), nullable=False)
    total = db.Column(db.Integer, nullable=False)
    filters_json = db.Column(db.Text, nullable=False, default="{}")
    summary_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)

    items = db.relationship(
        "QuerySnapshotItem",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="QuerySnapshotItem.position",
    )

    def is_expired(self, now=None):
        return (now or datetime.now()) >= self.expires_at

    def to_meta(self):
        return {
            "snapshot_token": self.token,
            "snapshot_created_at": iso(self.created_at),
            "snapshot_expires_at": iso(self.expires_at),
            "sort": self.sort,
            "order": self.order,
        }


class QuerySnapshotItem(db.Model):
    __tablename__ = "query_snapshot_items"
    __table_args__ = (
        db.UniqueConstraint("snapshot_id", "position", name="uq_snapshot_position"),
    )

    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(
        db.Integer,
        db.ForeignKey("query_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 不建外键约束: 源记录被删除后快照仍然保留其位置, 保证页数/总数不位移
    measurement_id = db.Column(db.Integer, nullable=False)
    position = db.Column(db.Integer, nullable=False)

    snapshot = db.relationship("QuerySnapshot", back_populates="items")


def new_snapshot_token():
    """URL 安全的随机令牌, 32 字符, 冲突概率可忽略。"""
    return secrets.token_urlsafe(24)
