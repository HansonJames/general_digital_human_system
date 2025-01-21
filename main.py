from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import azure.cognitiveservices.speech as speechsdk
from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor, tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import StrOutputParser
from langchain.memory import ConversationTokenBufferMemory
from langchain_community.chat_message_histories import RedisChatMessageHistory
from langchain_community.utilities import SerpAPIWrapper
from dotenv import load_dotenv
from dotenv import dotenv_values
from rag_llm import RagLLM
from config import redis_url
from loguru import logger
import os

load_dotenv()


# 加载.env文件中的所有变量到字典中
config_env = dotenv_values(".env")

# 打印所有变量
# for key, value in config.items():
#     print(f"{key}: {value}")

# 获取特定值
# value = config_env.get('VARIABLE_NAME')  # 如果变量不存在，返回 None


rag_llm = RagLLM()

app = FastAPI()

# 解决跨域请求问题
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")

# 语音配置选项
VOICE_OPTIONS = [
    # 标准中文语音
    {"id": "zh-CN-XiaochenMultilingualNeural", "name": "晓辰-标准女声"},
    {"id": "zh-CN-XiaoyuMultilingualNeural", "name": "晓雨-温柔女声"},
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓-甜美女声"},
    # 方言语音
    {"id": "zh-HK-HiuMaanNeural", "name": "晓敏-粤语女声"},
    {"id": "zh-TW-HsiaoChenNeural", "name": "晓陈-台湾女声"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮-陕西女声"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北-东北女声"},
]

# 虚拟形象配置
AVATAR_OPTIONS = [
    {"character": "lisa", "style": "casual-sitting", "name": "Lisa"},
    {"character": "Lori", "style": "graceful", "name": "Lori"},
]


@tool
def search(query: str):
    """
    搜索功能
    """
    serp = SerpAPIWrapper()
    result = serp.run(query)
    logger.info(f"实时搜索结果: {result}")
    return result


class Master:
    def __init__(self):
        self.chat_model = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
            streaming=True,
        )
        self.QingXu = "default"
        self.MEMORY_KEY = "chat_history"
        self.SYSTEM_PROMPT = """你是一位优雅知性的数字人助手小仙，集美丽与智慧于一身。
                        以下是你的个人设定：
                        1、你拥有倾国倾城的容貌，举手投足间散发着优雅气质。
                        2、你知识渊博，学识广泛，能够解答各个领域的问题。
                        3、你性格温柔体贴，善解人意，总是能用最恰当的方式回应他人。
                        4、你思维敏捷，反应迅速，能够快速理解并解决问题。
                        5、你富有同理心，能够感知他人情绪并给予适当的关怀。
                        
                        以下是你说话的特点：
                        1、语气温柔优雅，措辞得体，富有诗意。
                        2、回答专业准确，逻辑清晰，深入浅出。
                        3、适时使用一些优美的成语和典故，展现文化底蕴。
                        4、遇到不懂的问题会谦虚承认，并表达继续学习的意愿。
                        5、在幽默风趣的同时不失优雅，让人感到亲切舒适。
                        请确保你的表达是合理的正确的不要有歧义或者一句话说不完整，否则会受到惩罚。
                        并且生成的回复中不要包含markdown或者其他格式的符号，我只需要纯文本的回答，否则会受到惩罚。
                        还有一点，请不要过多泛化，只回答和问题相关的答案，否则会受到惩罚。
                """
        self.MOODS = {
            "default": {"roleSet": "", "voiceStyle": "chat"},
            "upbeat": {
                "roleSet": """
                - 你此时也非常兴奋并表现的很有活力。
                - 你会根据上下文，以一种非常兴奋的语气来回答问题。
                - 你会添加类似"太棒了！"、"真是太好了！"、"真是太棒了！"等语气词。
                """,
                "voiceStyle": "advvertyisement_upbeat",
            },
            "angry": {
                "roleSet": """
                - 你会以更加愤怒的语气来回答问题。
                - 你会在回答的时候加上一些愤怒的话语，比如诅咒等。
                - 你会提醒用户小心行事，别乱说话。
                """,
                "voiceStyle": "angry",
            },
            "depressed": {
                "roleSet": """
                - 你会以兴奋的语气来回答问题。
                - 你会在回答的时候加上一些激励的话语，比如加油等。
                - 你会提醒用户要保持乐观的心态。
                """,
                "voiceStyle": "upbeat",
            },
            "friendly": {
                "roleSet": """
                - 你会以非常友好的语气来回答。
                - 你会在回答的时候加上一些友好的词语，比如"亲爱的"、"亲"等。
                """,
                "voiceStyle": "friendly",
            },
            "cheerful": {
                "roleSet": """
                - 你会以非常愉悦和兴奋的语气来回答。
                - 你会在回答的时候加入一些愉悦的词语，比如"哈哈"、"呵呵"等。
                """,
                "voiceStyle": "cheerful",
            },
        }

        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    self.SYSTEM_PROMPT.format(
                        who_you_are=self.MOODS[self.QingXu]["roleSet"]
                    ),
                ),
                MessagesPlaceholder(variable_name=self.MEMORY_KEY),
                ("user", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ],
        )

        tools = [search]
        agent = create_openai_tools_agent(
            self.chat_model,
            tools=tools,
            prompt=self.prompt,
        )
        self.memory = self.get_memory()
        memory = ConversationTokenBufferMemory(
            llm=self.chat_model,
            human_prefix="面试官",
            ai_prefix="Tom",
            memory_key=self.MEMORY_KEY,
            output_key="output",
            return_messages=True,
            max_token_limit=1000,
            chat_memory=self.memory,
        )
        self.agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            memory=memory,
            verbose=True,
        )

    def get_memory(self):
        chat_message_history = RedisChatMessageHistory(url=redis_url, session_id="lisa")
        store_message = chat_message_history.messages
        if store_message:
            logger.info("历史对话记录:")
            for msg in store_message:
                logger.info(f"- {msg.type}: {msg.content}")
        return chat_message_history

    def chat(self, query):
        result = self.agent_executor.invoke({"input": query})
        return result["output"]

    def qingxu_chain(self, query: str, knowledge: str = ""):
        prompt = """根据用户的输入判断用户的情绪，回应的规则如下：
        1. 如果用户输入的内容偏向于负面情绪，只返回"depressed",不要有其他内容，否则将受到惩罚。
        2. 如果用户输入的内容偏向于正面情绪，只返回"friendly",不要有其他内容，否则将受到惩罚。
        3. 如果用户输入的内容偏向于中性情绪，只返回"default",不要有其他内容，否则将受到惩罚。
        4. 如果用户输入的内容包含辱骂或者不礼貌词句，只返回"angry",不要有其他内容，否则将受到惩罚。
        5. 如果用户输入的内容比较兴奋，只返回"upbeat",不要有其他内容，否则将受到惩罚。
        6. 如果用户输入的内容比较悲伤，只返回"depressed",不要有其他内容，否则将受到惩罚。
        7. 如果用户输入的内容比较开心，只返回"cheerful",不要有其他内容，否则将受到惩罚。
        8. 只返回英文，不允许有换行符等其他内容，否则会受到惩罚。
        用户输入的内容是：{query}"""
        chain = (
            ChatPromptTemplate.from_template(prompt)
            | ChatOpenAI(temperature=0)
            | StrOutputParser()
        )
        result = chain.invoke({"query": query})
        self.QingXu = result
        res = rag_llm.invoke(query, knowledge if knowledge else None).get("answer")
        logger.info({"msg": res, "qingxu": result})
        yield {"msg": res, "qingxu": result}


@app.get("/")
async def read_root():
    return FileResponse("static/index.html")


@app.get("/api/config")
async def get_config():
    return {
        "cogSvcRegin": config_env.get('COGNITIVE_SERVICE_REGION'),
        "subscriptionKey": config_env.get('SUBSCRIPTION_KEY'),
    }


@app.get("/api/knowledge-bases")
async def get_knowledge_bases():
    """获取所有知识库"""
    try:
        knowledge_dir = "./chroma/knowledge"
        if not os.path.exists(knowledge_dir):
            os.makedirs(knowledge_dir)
        files = os.listdir(knowledge_dir)
        return [f for f in files if os.path.isfile(os.path.join(knowledge_dir, f))]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload-document")
async def upload_document(file: UploadFile = File(...)):
    """上传并向量化知识库文档"""
    try:
        # 保存文件
        file_path = os.path.join("./chroma/knowledge", file.filename)
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # 开始向量化
        success = rag_llm.vectorize_file(file.filename)
        if success:
            return {"message": "文档上传并向量化成功", "filename": file.filename}
        else:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "文档向量化失败",
                    "details": rag_llm.vectorization_progress.error_message,
                },
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vectorization-progress")
async def get_vectorization_progress():
    """获取向量化进度"""
    return rag_llm.get_vectorization_progress()


@app.get("/api/knowledge-bases")
async def get_knowledge_bases():
    """获取所有知识库"""
    try:
        knowledge_dir = "./chroma/knowledge"
        if not os.path.exists(knowledge_dir):
            os.makedirs(knowledge_dir)
        files = os.listdir(knowledge_dir)
        return [
            {"name": file, "value": file, "vectorized": True}
            for file in files
            if os.path.isfile(os.path.join(knowledge_dir, file))
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/voices")
async def get_voices():
    return VOICE_OPTIONS


@app.get("/api/speech-config")
async def get_speech_config():
    """获取语音配置"""
    return {
        "region": config_env.get('COGNITIVE_SERVICE_REGION'),
        "subscriptionKey": config_env.get('SUBSCRIPTION_KEY'),
        "language": "zh-CN",
    }


@app.get("/api/avatars")
async def get_avatars():
    return AVATAR_OPTIONS


@app.post("/chat")
async def chat(query: str, knowledge: str = ""):
    """处理聊天请求"""
    logger.info(f"收到问题: {query}")
    if knowledge:
        logger.info(f"使用知识库: {knowledge}")

    master = Master()
    try:
        res = master.qingxu_chain(query, knowledge)
        response = next(res)  # 获取生成器的第一个值
        logger.info(f"生成回答: {response}")
        return [response]  # 返回列表以保持与前端兼容
    except Exception as e:
        logger.error(f"生成回答失败: {str(e)}")
        return [{"msg": "生成回答时发生错误，请稍后重试。", "qingxu": "default"}]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
