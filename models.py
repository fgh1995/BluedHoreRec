import re
from enum import Enum
from typing import List, Dict, Pattern
from collections import defaultdict


class LiveMessageParser:
    """直播消息解析器，用于提取关键词和识别消息类型"""

    # 匹配 @(word:xxx) 格式的正则表达式
    WORD_PATTERN = r"@\(word:([^)]+)\)"

    class MessageType(Enum):
        """消息类型枚举（带匹配规则）"""
        ARTIFICE = ".*(触发金火时刻|炼化获得|倍炼化).*"
        CHAMELEON_LIFE = ".*(插画师|医生|拳击手|机长|超级影帝).*"  #
        A_DESERT_DREAM = ".*(烛光|花灯|敦煌恋歌|走进敦煌|九色神鹿|舞动敦煌|飞天传说|隐藏款).*"  # 敦煌梦境
        HOLY_SWORDSMAN = ".*(神圣体魄|黄金手套|黄金战靴|黄金头盔|黄金铠甲|圣剑降临).*"  # 圣剑士
        PRIMARY_TREASURE = ".*初级宝藏.*"  # 初级宝藏
        ADVANCED_TREASURE = ".*高级宝藏.*"  # 高级宝藏
        GLOWING_TREASURE = ".*璀璨宝藏.*"  # 璀璨宝藏
        MULTIPLIER_REWARD = "恭喜.*触发.*倍.*获得.*豆.*"  # 倍数奖励
        UNKNOWN = ""  # 未知类型

        def get_regex_pattern(self) -> str:
            return self.value

    # 预编译正则表达式（性能优化）
    MESSAGE_PATTERNS: Dict[MessageType, Pattern] = {}

    @classmethod
    def init_patterns(cls):
        """初始化时预编译所有正则表达式"""
        for message_type in cls.MessageType:
            if message_type != cls.MessageType.UNKNOWN:
                cls.MESSAGE_PATTERNS[message_type] = re.compile(message_type.get_regex_pattern())

    @classmethod
    def determine_message_type(cls, message: str) -> MessageType:
        """根据正则匹配判断消息类型"""
        for message_type, pattern in cls.MESSAGE_PATTERNS.items():
            if pattern.search(message):
                return message_type
        return cls.MessageType.UNKNOWN

    @classmethod
    def convert_special_message(cls, message):
        """转换特殊格式的消息"""
        pattern = r'@\(word:([^)]+)\)'
        return re.sub(pattern, r'\1', message)


# 初始化静态正则表达式
LiveMessageParser.init_patterns()


class GiftRecord:
    def __init__(self, time="", user="", gift="", beans=0, count=0, multiple=1.0, gift_type=None):
        self.time = time
        self.user = user
        self.gift = gift
        self.beans = beans
        self.count = count
        self.multiple = multiple
        self.total = beans * count
        self.gift_type = gift_type or LiveMessageParser.MessageType.UNKNOWN


class LotteryRecord:
    def __init__(self, time, user, gift, multiple, beans, gift_type=None):
        self.time = time
        self.user = user
        self.gift = gift
        self.multiple = multiple
        self.beans = beans
        self.gift_type = gift_type or LiveMessageParser.MessageType.UNKNOWN


class EggRecord:
    def __init__(self, time, user, receiver, count, gift, beans, gift_type=None):
        self.time = time
        self.user = user
        self.receiver = receiver
        self.count = count
        self.gift = gift
        self.beans = beans
        self.gift_type = gift_type or LiveMessageParser.MessageType.UNKNOWN


class DataAnalyzer:
    GIFT_VALUES = {
        "神秘人": 38,
        "插画师": 198,
        "医生": 688,
        "拳击手": 2688,
        "机长": 5688,
        "超级影帝": 15888,
        "猴王仙丹": 8888
    }
    LUCKY_GIFT_TYPE = {
        "幸运围棋": 4.0,
        "幸运卡牌": 12.0,
        "幸运发财": 36.0,
        "幸运面具": 100.0
    }

    @classmethod
    def parse_gift_records(cls, line):

        pattern_goldfire = r'(\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}:\d{2}(?:\.\d+)?) @\(word:(.*?)\) 触发金火时刻！获得 @\(word:(.*?)\) \((\d+)豆\)x(\d+)'
        pattern_normal = r'(\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}:\d{2}(?:\.\d+)?) 恭喜 @\(word:(.*?)\) 炼化获得 @\(word:(.*?)\) \((\d+)豆\)x(\d+)'
        pattern_multiple = r'(\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}:\d{2}(?:\.\d+)?) 恭喜 @\(word:(.*?)\) 触发(\d+\.?\d*)倍炼化，获得 @\(word:(.*?)\) \((\d+)豆\)x(\d+)'
        # 尝试匹配所有可能的格式
        match = (re.match(pattern_goldfire, line) or
                 re.match(pattern_normal, line) or
                 re.match(pattern_multiple, line))
        if match:
            groups = match.groups()
            # 根据不同格式提取数据
            if len(groups) == 5:  # 金火时刻或普通炼化
                time, user, gift, beans, count = groups
                multiple = 1.0
            else:  # 倍率炼化
                time, user, multiple, gift, beans, count = groups
            beans = int(beans)
            count = int(count)
            return GiftRecord(
                time=time,
                user=user,
                gift=gift,
                beans=beans,
                count=count,
                multiple=float(multiple),
                gift_type='炼化礼物'
            )

    @classmethod
    def parse_lottery_record(cls, record):
        # 更严格的正则匹配
        pattern = (
            r"(?P<time>\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"  # 时间（支持毫秒）
            r"恭喜@\(word:(?P<user>\w+)\)"  # 用户
            r"触发@\(word:(?P<count>\d+)\)倍，"  # 倍数
            r"获得@\(word:(?P<beans>\d+)\)豆"  # 豆数
        )

        match = re.search(pattern, record)

        if match:
            # 提取数据
            time = match.group("time")
            user = match.group("user")
            beans = int(match.group("beans"))
            count = int(match.group("count"))

            # 计算倍数
            multiple = float(count)
            REVERSE_GIFT_MAP = {v: k for k, v in cls.LUCKY_GIFT_TYPE.items()}
            # 计算单倍豆数，并匹配礼物名称
            single_beans = beans / count
            gift_name = REVERSE_GIFT_MAP.get(int(single_beans))
            # 如果未匹配到礼物，默认返回单倍豆数
            if not gift_name:
                gift_name = f"{single_beans}豆/倍"
            return LotteryRecord(
                time=time,
                user=user.strip(),
                gift=gift_name,
                multiple=int(multiple),
                beans=int(beans),
                gift_type='幸运礼物'
            )

    @classmethod
    def parse_egg_record(cls, eggRecord):
        pattern = r'(\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}:\d{2}(?:\.\d+)?) @\(word:([^)]+)\) 送 @\(word:([^)]+)\) @\(word:(\d+)\) 个 @\(word:<扭蛋礼物>([^)]+)\)，.*'
        match = re.match(pattern, eggRecord)
        if match:
            time, user, receiver, count, gift = match.groups()
            beans = cls.GIFT_VALUES.get(gift.strip(), 0)
            return EggRecord(
                time=time,
                user=user,
                receiver=receiver,
                count=count,
                gift=gift.strip(),
                beans=beans,
                gift_type='扭蛋礼物'
            )
