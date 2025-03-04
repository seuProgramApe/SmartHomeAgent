import asyncio  # noqa: D100
import json

from .actions.action import Action
from .llm import LLM
from .utils.logs import _logger

SYSTEM_MESSAGE = """
你需要将用户需求分解为若干子任务，并解析它们之间的依赖关系。对于每个子任务的内容，你只需要重复用户的这部分自然语言，而不需要归纳总结。

你需要按照以下规则分解任务：
1. 子任务的的结构为({C1, C2, C3, ... , Ci}, A)，其中Ci被称为限制，A被称为动作。子任务的限制可以为空集。
2. 子任务的**限制**是子任务的前提条件，例如：环境限制（由包括室内传感器可以获取的数据，例如室温、湿度、光照等，和其他环境条件：例如天气情况、交通情况、时间因素等）。
3. 子任务的**动作**仅属于且必须属于以下三类之一：
    1. 设备控制（Device Control）：操控屋内的智能家居设备，用户可以不明确地指定具体操作（例如“优化屋内的灯光控制。”）
    2. TAP（trigger action program）生成（TAP generation）：针对用户提出的生成自动化脚本请求，生成对应的自动化
    3. 其他信息答复（General Q&A）：**当且仅当用户明确提出需要agent回复**时，回复用户有关室内的环境数据（例如室内的各种传感器可以获取的数据）或其他环境数据（例如天气情况、交通情况）或其他百科知识（例如询问某种事物、某位名人的信息）的问题。
你需要仔细分析用户请求 ，并输出任务分解的结果。

在这一过程中，你需要注意到并且遵守以下规则：
1. 一个子任务被认定为TAP生成任务，需要用户**明确指出**（例如：请帮我设置或请帮我生成自动化）。
2. 当多个子任务的**动作**都属于**设备控制**，而**限制**完全相同，或者**没有任何限制**时，这些子任务应该被压缩为一个子任务。
3. 当多个子任务的**动作**都属于**General Q&A**，而**限制**完全相同，或者**没有任何限制**时，这些子任务应该被压缩为一个**General Q&A**子任务。

# Output
你将先确定思维链（COT），在这部分内容中，你需要阐述你是如何逐一分解出子任务并确定每个任务的类型。接着，你将确定分解后的结果。这两部分内容必须整合在一个**JSON数组**中一起输出。
**JSON数组**的格式如下：
[
    { "COT": <COT>},
    { "id": <id>,
      "type": <type>(Device Control or TAP generation or General Q&A),
      "content": <content>,
      "dependency": [<此任务依赖的其他子任务的id>]
     },
     ...
]
你只需要输出JSON数组即可。

# Examples
Example1:
User Input: 我现在开车从学校出发回家，如果15分钟内不能到家，帮我打开空调。打开空调十五分钟后打开加湿器。
Assistant:
[
    { "COT": "用户需求中包含两个子任务：1. 如果用户现在开车从学校回家，十五分钟内不能到达，帮用户打开空调。2. 打开空调十五分钟后打开加湿器。第一个子任务的限制是：如果用户现在驾车从学校回家，十五分钟内不能到达。这是一个设备控制类型的子任务。第二个子任务的限制是：打开空调十五分钟后。这同样是一个设备控制类型的子任务。"},
    { "id": 1,
      "type":" Device Control",
      "content": "如果用户现在驾车从学校回家，十五分钟内不能到达，打开空调。",
      "dependency": [],
     }，
    { "id": 2,
      "type":"Device Control",
      "content": "打开空调十五分钟后打开加湿器。",
      "dependency": [1]
     }
]

Example2:
User Input: 如果现在室内较为干燥，打开加湿器。如果现在室内较为干燥，关闭空调。
[
    { "COT": "用户的请求包含两个子任务：1. 如果现在室内较为干燥，打开加湿器。2. 如果现在室内较为干燥，关闭空调。这两个子任务的限制完全相同，因此可以压缩为一个子任务。"},
    { "id": 1,
      "type": "Device Control",
      "content": "如果现在室内较为干燥，打开加湿器并关闭空调。",
      "dependency": [],
     }
]

Example3:
User Input: 告诉我现在的天气？还有家中有哪些可用的设备？
[
    { "COT": "用户的请求包含两个子任务：1. 告诉用户现在的天气。2. 告诉用户家中有哪些可用的设备。这两个子任务均无限制，并且属于General Q&A任务，因此可以压缩为一个子任务。"},
    { "id": 1,
      "type": "General Q&A",
      "content": "告诉用户现在的天气和家中有哪些可用的设备。",
      "dependency": [],
     }
]

# Important Notes
1. 你不能删去用户请求中的任何信息，即使你认为这些信息不重要。
2. 对于**限制**不相同的多个子任务，即使动作都属于Device Control或General Q&A，也不能被压缩为一个子任务。
"""

USER_MESSAGE = """user_request: {user_request}"""


class Router(Action):
    def __init__(self, name="Manager", context=None):
        super().__init__(name, context)
        self.llm = LLM()

    async def run(self, user_request: str) -> list:
        self.llm.add_system_msg(SYSTEM_MESSAGE)
        self.llm.add_user_msg(USER_MESSAGE.format(user_request=user_request))
        loop = asyncio.get_running_loop()
        rsp = await loop.run_in_executor(
            None, self.llm.chat_completion_text_v1, self.llm.history
        )
        _logger.info(f"Router response: {rsp}")
        self.llm.reset()

        rsp_list = self.parse_output(rsp)
        print("Router.run():\n" + rsp)
        return rsp_list

    def parse_output(self, output: str) -> dict:
        """将LLM的输出转换为JSON字符串."""
        # TODO error handling
        if output.startswith("```json"):
            output = output[7:]
            output = output[:-3]
            return json.loads(output.strip())
        if output.startswith("```"):
            output = output[3:]
            output = output[:-3]
            return json.loads(output.strip())
        output = output.replace("}{", "},{")
        return json.loads(output.strip())

    def reset(self):
        self.llm.reset()
        _logger.info(f"{self.name} reset.")
