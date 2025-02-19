from copy import deepcopy
from datetime import datetime, timedelta
from queue import Queue

from .context_assistant import get_all_context
from .environment import Environment
from .message import Message
from .utils.singleton import Singleton
from . import Router


class Subtask:
    def __init__(self, id, content, time=None, msg=None, type=None, dependency=None):
        self.id: int = id
        self.content: str = content
        self.finsih_time: str = time
        self.finish_msg: Message = msg
        self.type: str = type
        self.dependency: list[int] = dependency

    def toStr(self):
        return f"Subtask:id={self.id}, content={self.content}, type={self.type}, dependency={self.dependency!s}, finish_time={self.finsih_time}"


class Jarvis(metaclass=Singleton):
    def __init__(self):
        self.environment = Environment()
        self.flag = True
        self.last_message_from = None
        self.task_que: Queue[Subtask] = Queue()  # 等待完成的子任务队列
        self.rspls: list = []  # 用于汇总所有已经完成的子任务的最后返回信息的content
        self.subtaskls: list[Subtask] = []  # 用于汇总所有**已经完成的子任务**的详细信息
        self.curr_subtask: Subtask | None = None
        self.manager = Router.Router()

    async def task_decomposition(self, request):
        """当且仅当子任务队列为空且self.flag为True时调用此方法,分解复杂任务,将子任务加入子任务队列."""
        print("Run task decomposition")
        rsp_list = await self.manager.run(
            Message(
                role="Jarvis",
                content=request,
                send_to=["Manager"],
                sent_from="User",
                cause_by="UserInput",
            )
        )  # 返回分解任务后的子任务list
        for task in rsp_list:
            if "id" not in task:
                continue
            newSubtask = Subtask(
                id=task["id"],
                content=task["content"],
                type=task["type"],
                dependency=task["dependency"],
            )
            self.task_que.put(newSubtask)

    async def process(self, request: str):
        if self.task_que.empty() and self.flag:
            # 子任务队列为空且所有子任务都已经完成
            await self.task_decomposition(request)

        if self.flag:  # 李安：如果flag为true，向环境发布的信息是用户输入，说明上一次的消息是由用户发出的请求，所以这次的消息要发给Manager
            subtask: Subtask = self.task_que.get(block=False)  # 获取新任务
            self.curr_subtask = subtask
            print(f"Execute new subtask: {subtask.content}")
            type = subtask.type
            if type == "TAP generation":
                await self.environment.publish_message(
                    Message(
                        role="Manager",
                        content=subtask.content,
                        send_to=["TAPGenerator"],
                        sent_from="User",
                        cause_by="UserInput",
                    )
                )
            elif type == "Device Control":
                await self.environment.publish_message(
                    Message(
                        role="Manager",
                        content=subtask.content,
                        send_to=["DeviceControler"],
                        sent_from="User",
                        cause_by="UserInput",
                    )
                )
            elif type == "General Q&A":
                await self.environment.publish_message(
                    Message(
                        role="Manager",
                        content=subtask.content,
                        send_to=["Chatbot"],
                        sent_from="User",
                        cause_by="UserInput",
                    )
                )
            else:
                raise Exception("Unknown subtask type")
        elif self.last_message_from is None:
            raise Exception("last_message_from is None")
        else:  # 李安：如果flag为false，向环境发布的信息是用户回复，说明上一次的消息是由某个角色发出的向用户询问，所以这次的消息也要发给这个角色
            await self.environment.publish_message(
                Message(
                    role="Jarvis",
                    content=request,
                    send_to=[self.last_message_from],
                    sent_from="User",
                    cause_by="UserResponse",
                )
            )
        msg, flag = await self.environment.run()
        if flag:  # 李安：如果环境运行得到的信息中的flag是True，说明resp_type是Finish，本次任务已经完成，需要重置环境
            self.flag = True
            self.last_message_from = None
            self.environment.reset()

            self.rspls.append(msg.content)  # 将本次任务的返回信息加入rspls

            now = datetime.now() + timedelta(hours=8)  # 正式发布时可能需要修改时区
            formatted_time = now.strftime("%Y-%m-%d %H:%M:%S")  # 该任务完成的格式化时间

            curr_subtask: Subtask = deepcopy(self.curr_subtask)
            curr_subtask.finsih_time = formatted_time
            curr_subtask.finish_msg = msg
            self.subtaskls.append(curr_subtask)  # 该子任务已经完成，加入subtaskls

            print(f"{self.curr_subtask.content} done.")
            print("self.subtaskls(jarvis.py, line 119):")
            for st in self.subtaskls:
                print(st.toStr())
            if self.task_que.empty():  # 所有子任务都已经处理完毕
                print("All subtasks done.")
                rsp = deepcopy(self.rspls)
                self.rspls.clear()
                self.subtaskls.clear()  # 清空rspls和subtaskls
                return rsp
            return None
        # 如果环境运行得到的信息中的flag是False，说明resp_type是AskUser，本次任务还未完成，需要继续
        self.flag = False
        self.last_message_from = (
            msg.role
        )  # msg.role记录了上一次信息是由哪个角色发出的，下一次信息要发给这个角色
        return msg.content

    async def run(self, request: str):
        if request == "刷新":
            get_all_context()
            self.flag = True
            self.last_message_from = None
            self.task_que = Queue()
            self.rspls = []
            self.environment.reset()
            self.curr_subtask: str = None
            return "请问需要什么帮助？"

        rsp = await self.process(request)
        while rsp is None:
            rsp = await self.process(request)
        if isinstance(rsp, list):
            return self.printList(rsp)
        return rsp

    def printList(self, ls: list) -> str:
        return "\n".join(f"Subtask {i} response: {msg}" for i, msg in enumerate(ls))


JARVIS = Jarvis()
