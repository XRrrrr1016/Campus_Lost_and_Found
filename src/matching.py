"""Versioned deterministic offline AI simulator; never determines ownership."""
import re
import unicodedata
from datetime import date

ENGINE_VERSION = 'offline-text-v2'
SUPPORTED_ENGINES = {'offline-text-v1', 'offline-text-v2'}
DEFAULT_WEIGHTS = {'category': .25, 'location': .20, 'color': .15, 'time': .15, 'text': .25}
LABELS = {'category': '类别', 'location': '地点', 'color': '颜色', 'time': '时间', 'text': '文字描述'}
UNKNOWN = {'', '未知', '不详', '不确定', '其他', '无'}
SYNONYMS = {'图书室': '图书馆', '餐厅': '食堂', '运动场': '操场', '一食堂': '第一食堂',
            '藏青': '蓝', '蓝色': '蓝', '黑色': '黑', '白色': '白', '红色': '红', '绿色': '绿',
            '灰色': '灰', '黄色': '黄', '紫色': '紫', '一卡通': '校园卡', '双肩包': '背包'}


def normalize(value, engine_version=ENGINE_VERSION):
    if engine_version not in SUPPORTED_ENGINES:
        raise ValueError('Unsupported matching engine')
    text = unicodedata.normalize('NFKC', str(value or '')).lower().strip()
    for source, target in SYNONYMS.items():
        # Preserve both the replacement and its original order for legacy snapshots.
        if source == '一食堂' and engine_version == 'offline-text-v2':
            text = re.sub(r'(?<!第)一食堂', target, text)
        else:
            text = text.replace(source, target)
    return re.sub(r'[\W_]+', '', text)


def known(value, engine_version=ENGINE_VERSION):
    return normalize(value, engine_version) not in UNKNOWN


def similarity(left, right, engine_version=ENGINE_VERSION):
    left, right = normalize(left, engine_version), normalize(right, engine_version)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return .85
    grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)} or {s}
    a, b = grams(left), grams(right)
    return 2 * len(a & b) / (len(a) + len(b))


def score_pair(left, right, weights, engine_version=ENGINE_VERSION):
    """Return a stable JSON result. Missing fields do not inflate the score."""
    values, evidence, present = {}, [], 0
    is_known = lambda value: known(value, engine_version)
    for field in ('category', 'location', 'color', 'text', 'time'):
        if field == 'text':
            a, b = left.get('description', ''), right.get('description', '')
        elif field == 'time':
            a, b = left.get('date_from', ''), right.get('date_from', '')
        else:
            a, b = left.get(field, ''), right.get(field, '')
        available = is_known(a) and is_known(b)
        value = 0.0
        if available:
            if field == 'time':
                try:
                    a0, a1 = date.fromisoformat(a), date.fromisoformat(left.get('date_to') or a)
                    b0, b1 = date.fromisoformat(b), date.fromisoformat(right.get('date_to') or b)
                    gap = max(0, (a0 - b1).days, (b0 - a1).days)
                    value = max(0, 1 - gap / 14)
                except ValueError:
                    available = False
            elif field in ('category', 'color'):
                value = float(normalize(a, engine_version) == normalize(b, engine_version))
            else:
                value = similarity(a, b, engine_version)
        if weights.get(field, 0) > 0:
            if available:
                present += 1
                evidence.append(f'{LABELS[field]}{"一致" if value >= .85 else "接近" if value >= .4 else "存在差异"}')
            values[field] = round(value, 6)
    score = sum(weights.get(f, 0) * v for f, v in values.items()) * 100
    conflicts = []
    if weights.get('category', 0) and is_known(left.get('category')) and is_known(right.get('category')) and values.get('category') == 0:
        score = min(score, 30)
        conflicts.append('类别冲突，降低分数')
    if weights.get('color', 0) and is_known(left.get('color')) and is_known(right.get('color')) and values.get('color') == 0:
        score = min(score, 49)
        conflicts.append('颜色冲突，降低分数')
    if weights.get('time', 0) and is_known(left.get('date_from')) and is_known(right.get('date_from')) and values.get('time') == 0:
        score = min(score, 49)
        conflicts.append('时间跨度过大')
    if present < 3:
        score = min(score, 35)
        confidence = 'insufficient'
        evidence.append('有效可比字段少于三项，信息不足，拒绝判断归属')
    else:
        confidence = 'high' if score >= 75 else 'medium' if score >= 50 else 'low'
    return {'score': round(score, 2), 'confidence': confidence, 'fields': values,
            'explanation': '；'.join(evidence + conflicts) + '。仅作候选，请核验未公开特征。'}
