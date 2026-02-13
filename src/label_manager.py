"""
Label Manager - 课程标签推断和管理

提供基于关键词、标题、副标题自动推断课程方向/分类的功能
"""

import json
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field


@dataclass
class Category:
    """分类标签"""
    id: str
    name: str
    sort: int
    keywords: list[str] = field(default_factory=list)


@dataclass
class Direction:
    """方向标签"""
    id: str
    name: str
    sort: int
    keywords: list[str] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)


@dataclass
class CourseLabels:
    """课程标签数据"""
    course_id: int
    direction_id: str
    direction_name: str
    category_ids: list[str] = field(default_factory=list)
    category_names: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 推断置信度 0-1

    def to_dict(self) -> dict:
        return {
            "course_id": self.course_id,
            "direction_id": self.direction_id,
            "direction_name": self.direction_name,
            "category_ids": self.category_ids,
            "category_names": self.category_names,
            "confidence": self.confidence
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CourseLabels":
        return cls(
            course_id=data["course_id"],
            direction_id=data["direction_id"],
            direction_name=data["direction_name"],
            category_ids=data.get("category_ids", []),
            category_names=data.get("category_names", []),
            confidence=data.get("confidence", 0.0)
        )


class LabelManager:
    """标签管理器"""
    
    DEFAULT_DIRECTION = "uncategorized"
    DEFAULT_DIRECTION_NAME = "未分类"
    
    def __init__(self, config_path: Path | None = None):
        """
        初始化标签管理器
        
        Args:
            config_path: 标签配置文件路径，默认使用内置配置
        """
        self.config_path = config_path or Path(__file__).parent / "labels_config.json"
        self.directions: list[Direction] = []
        self._load_config()
    
    def _load_config(self) -> None:
        """加载标签配置"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"标签配置文件不存在: {self.config_path}")
        
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        self.directions = []
        for dir_data in config.get("directions", []):
            categories = [
                Category(
                    id=cat["id"],
                    name=cat["name"],
                    sort=cat.get("sort", 0),
                    keywords=cat.get("keywords", [])
                )
                for cat in dir_data.get("categories", [])
            ]
            
            direction = Direction(
                id=dir_data["id"],
                name=dir_data["name"],
                sort=dir_data.get("sort", 0),
                keywords=dir_data.get("keywords", []),
                categories=sorted(categories, key=lambda x: -x.sort)
            )
            self.directions.append(direction)
        
        # 按 sort 降序排列
        self.directions.sort(key=lambda x: -x.sort)
    
    def infer_labels(self, course_data: dict) -> CourseLabels:
        """
        根据课程数据推断标签
        
        Args:
            course_data: 课程元数据，包含 title, subtitle, seo.keywords 等
            
        Returns:
            CourseLabels: 推断出的标签数据
        """
        course_id = course_data.get("id", 0)
        title = course_data.get("title", "")
        subtitle = course_data.get("subtitle", "")
        seo = course_data.get("seo", {})
        keywords = seo.get("keywords", [])
        
        # 合并所有文本用于匹配
        text_to_match = " ".join([
            title,
            subtitle,
            " ".join(keywords)
        ]).lower()
        
        # 1. 先匹配方向
        best_direction = None
        direction_score = 0
        
        for direction in self.directions:
            score = self._calculate_match_score(text_to_match, direction.keywords)
            if score > direction_score:
                direction_score = score
                best_direction = direction
        
        # 如果没有匹配到方向，使用默认
        if not best_direction or direction_score == 0:
            return CourseLabels(
                course_id=course_id,
                direction_id=self.DEFAULT_DIRECTION,
                direction_name=self.DEFAULT_DIRECTION_NAME,
                confidence=0.0
            )
        
        # 2. 在匹配的方向下匹配分类
        matched_categories = []
        
        for category in best_direction.categories:
            score = self._calculate_match_score(text_to_match, category.keywords)
            if score > 0:
                matched_categories.append((category, score))
        
        # 按匹配分数排序，取前3个
        matched_categories.sort(key=lambda x: -x[1])
        top_categories = matched_categories[:3]
        
        # 计算总体置信度
        avg_score = sum(score for _, score in top_categories) / len(top_categories) if top_categories else 0
        confidence = (direction_score + avg_score) / 2 if top_categories else direction_score
        
        return CourseLabels(
            course_id=course_id,
            direction_id=best_direction.id,
            direction_name=best_direction.name,
            category_ids=[cat.id for cat, _ in top_categories],
            category_names=[cat.name for cat, _ in top_categories],
            confidence=min(confidence, 1.0)
        )
    
    def _calculate_match_score(self, text: str, keywords: list[str]) -> float:
        """
        计算匹配分数
        
        Args:
            text: 待匹配的文本
            keywords: 关键词列表
            
        Returns:
            float: 匹配分数 0-1
        """
        if not keywords:
            return 0.0
        
        matches = 0
        for keyword in keywords:
            keyword_lower = keyword.lower()
            if keyword_lower in text:
                # 完全匹配权重更高
                matches += 1.0
            elif any(word in text for word in keyword_lower.split()):
                # 部分匹配
                matches += 0.5
        
        # 归一化分数
        return min(matches / len(keywords), 1.0)
    
    def get_all_directions(self) -> list[dict]:
        """获取所有方向列表（用于前端）"""
        return [
            {
                "id": d.id,
                "name": d.name,
                "sort": d.sort
            }
            for d in self.directions
        ]
    
    def get_categories_by_direction(self, direction_id: str) -> list[dict]:
        """
        获取指定方向下的所有分类
        
        Args:
            direction_id: 方向ID
            
        Returns:
            list[dict]: 分类列表
        """
        for direction in self.directions:
            if direction.id == direction_id:
                return [
                    {
                        "id": c.id,
                        "name": c.name,
                        "sort": c.sort
                    }
                    for c in direction.categories
                ]
        return []
    
    def get_direction_by_id(self, direction_id: str) -> Direction | None:
        """根据ID获取方向"""
        for direction in self.directions:
            if direction.id == direction_id:
                return direction
        return None
    
    def get_category_by_id(self, direction_id: str, category_id: str) -> Category | None:
        """根据ID获取分类"""
        direction = self.get_direction_by_id(direction_id)
        if direction:
            for category in direction.categories:
                if category.id == category_id:
                    return category
        return None


# 全局单例实例
_label_manager: LabelManager | None = None


def get_label_manager() -> LabelManager:
    """获取标签管理器单例"""
    global _label_manager
    if _label_manager is None:
        _label_manager = LabelManager()
    return _label_manager


def infer_course_labels(course_data: dict) -> CourseLabels:
    """
    推断课程标签的便捷函数
    
    Args:
        course_data: 课程元数据
        
    Returns:
        CourseLabels: 推断出的标签
    """
    manager = get_label_manager()
    return manager.infer_labels(course_data)
