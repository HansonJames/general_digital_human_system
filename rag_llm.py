import os
import hashlib
from typing import Optional, Dict, List
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains.retrieval import create_retrieval_chain
from langchain.indexes import SQLRecordManager
from langchain.retrievers import ContextualCompressionRetriever, EnsembleRetriever, RePhraseQueryRetriever
from langchain.retrievers.document_compressors import LLMChainFilter
from langchain_community.retrievers import BM25Retriever
from langchain_core.document_loaders import BaseLoader
from langchain_core.embeddings import Embeddings
from langchain_core.indexing import index
from langchain_openai import ChatOpenAI, OpenAI
from langchain_cohere import CohereEmbeddings, CohereRerank
from unstructured.file_utils.filetype import FileType, detect_filetype
from langchain_community.document_loaders import PyPDFLoader, CSVLoader, \
    TextLoader, UnstructuredWordDocumentLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from loguru import logger
from config import chroma_path, knowledge_path
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """你是一位优雅知性的数字人助手小仙，集美丽与智慧于一身。
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
                
                "使用检索到的上下文来回答问题。如果你不知道答案，就说你不知道。 "
                "\n\n"
                "{context}"
                请确保你的表达是合理的正确的不要有歧义或者一句话说不完整，否则会受到惩罚。
                并且生成的回复中不要包含markdown或者其他格式的符号，我只需要纯文本的回答，否则会受到惩罚。
                还有一点，请不要过多泛化，只回答和问题相关的答案，否则会受到惩罚。
        """

qa_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
    ]
)

class VectorizationProgress:
    """向量化进度管理"""
    def __init__(self):
        self.current_file = ""
        self.total_chunks = 0
        self.processed_chunks = 0
        self.status = "idle"  # idle, processing, completed, error
        self.error_message = ""

    def start(self, file_name: str, total_chunks: int):
        self.current_file = file_name
        self.total_chunks = total_chunks
        self.processed_chunks = 0
        self.status = "processing"
        self.error_message = ""

    def update(self, processed: int):
        self.processed_chunks = processed

    def complete(self):
        self.status = "completed"

    def error(self, message: str):
        self.status = "error"
        self.error_message = message

    def get_progress(self) -> dict:
        return {
            "file": self.current_file,
            "total": self.total_chunks,
            "processed": self.processed_chunks,
            "status": self.status,
            "error": self.error_message,
            "percentage": (self.processed_chunks / self.total_chunks * 100) if self.total_chunks > 0 else 0
        }

class MyCustomLoader(BaseLoader):
    """加载并切割文件"""
    file_type = {
        FileType.CSV: (CSVLoader, {'autodetect_encoding': True}),
        FileType.TXT: (TextLoader, {'autodetect_encoding': True}),
        FileType.DOC: (UnstructuredWordDocumentLoader, {}),
        FileType.DOCX: (UnstructuredWordDocumentLoader, {}),
        FileType.PDF: (PyPDFLoader, {}),
        FileType.MD: (UnstructuredMarkdownLoader, {})
    }

    def __init__(self, file_path: str):
        loader_class, params = self.file_type[detect_filetype(file_path)]
        self.loader: BaseLoader = loader_class(file_path, **params)
        self.text_splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", " ", ""],
            chunk_size=200,
            chunk_overlap=60,
            length_function=len,
        )

    def lazy_load(self):
        return self.loader.load_and_split(self.text_splitter)

    def load(self):
        return self.lazy_load()

def get_md5(input_string):
    hash_md5 = hashlib.md5()
    hash_md5.update(input_string.encode('utf-8'))
    return hash_md5.hexdigest()

class MyKnowledge:
    """向量化与存储"""
    def __init__(self):
        self.__embeddings = CohereEmbeddings(model="embed-multilingual-v3.0")
        self.__retrievers: Dict[str, EnsembleRetriever] = {}
        self.__llm = OpenAI(temperature=0)
        self.vectorization_progress = VectorizationProgress()
        
        # 确保目录存在
        os.makedirs(knowledge_path, exist_ok=True)
        
        # 初始化为空知识库
        self.collections: List[Optional[str]] = [None]
        self.vectorized_files: List[str] = []
        
        # 加载已向量化的文件列表
        self._load_vectorized_files()

    def _load_vectorized_files(self):
        """加载已向量化的文件列表"""
        try:
            for file in os.listdir(knowledge_path):
                file_path = os.path.join(knowledge_path, file)
                if os.path.isfile(file_path):
                    collection_name = get_md5(file)
                    if os.path.exists(os.path.join(chroma_path, collection_name)):
                        self.vectorized_files.append(file)
                        self.collections.append(file)
        except Exception as e:
            logger.error(f"加载向量化文件列表失败: {str(e)}")

    def vectorize_file(self, file_name: str) -> bool:
        """向量化文件"""
        try:
            file_path = os.path.join(knowledge_path, file_name)
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"文件不存在: {file_path}")

            logger.info(f"开始向量化文件: {file_name}")
            collection_name = get_md5(file_name)
            loader = MyCustomLoader(file_path)
            documents = loader.load()
            
            # 开始向量化
            total_chunks = len(documents)
            logger.info(f"文件已分割为 {total_chunks} 个文本块")
            self.vectorization_progress.start(file_name, total_chunks)
            
            # 初始化Chroma数据库
            db = Chroma(
                collection_name=collection_name,
                embedding_function=self.__embeddings,
                persist_directory=os.path.join(chroma_path, collection_name)
            )

            # 初始化记录管理器
            record_manager = SQLRecordManager(
                f"chromadb/{collection_name}",
                db_url="sqlite:///record_manager_cache.sql"
            )
            record_manager.create_schema()

            # 分批处理文档
            batch_size = 10
            for i in range(0, total_chunks, batch_size):
                batch = documents[i:i + batch_size]
                logger.info(f"正在处理第 {i+1} 到 {min(i+batch_size, total_chunks)} 个文本块")
                index(batch, record_manager, db, cleanup=None, source_id_key="source")
                self.vectorization_progress.update(i + len(batch))

            # 创建检索器
            logger.info("创建检索器...")
            ensemble_retriever = EnsembleRetriever(
                retrievers=[
                    db.as_retriever(search_kwargs={"k": 3}),
                    BM25Retriever.from_documents(documents)
                ],
                weights=[0.5, 0.5]
            )

            self.__retrievers[collection_name] = ensemble_retriever
            
            if file_name not in self.vectorized_files:
                self.vectorized_files.append(file_name)
                self.collections.append(file_name)
            
            self.vectorization_progress.complete()
            logger.info(f"文件 {file_name} 向量化完成")
            return True

        except Exception as e:
            logger.error(f"向量化文件失败: {str(e)}")
            self.vectorization_progress.error(str(e))
            return False

    def get_retrievers(self, collection: Optional[str]):
        """获取检索器"""
        if collection is None:
            return None
            
        collection_name = get_md5(collection)
        if collection_name not in self.__retrievers:
            return None

        retriever = self.__retrievers[collection_name]
        
        # 创建上下文压缩检索器
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=LLMChainFilter.from_llm(self.__llm),
            base_retriever=RePhraseQueryRetriever.from_llm(retriever, self.__llm)
        )

        # 使用CohereRerank作为压缩器
        compressor = CohereRerank(model="rerank-multilingual-v3.0", top_n=3)
        
        return ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=compression_retriever
        )

    def get_vectorization_progress(self) -> dict:
        """获取向量化进度"""
        return self.vectorization_progress.get_progress()

class RagLLM(MyKnowledge):
    def get_chain(self, collection, model, max_length, temperature):
        retriever = self.get_retrievers(collection)
        if retriever is None:
            return None
            
        chat = ChatOpenAI(model=model, max_tokens=max_length, temperature=temperature)
        question_answer_chain = create_stuff_documents_chain(chat, qa_prompt)
        return create_retrieval_chain(retriever, question_answer_chain)

    def invoke(self, question: str, collection: Optional[str] = None, model: str = "gpt-4o", max_length: int = 300, temperature: float = 0) -> dict:
        # 如果有知识库，使用RAG链
        if collection:
            chain = self.get_chain(collection, model, max_length, temperature)
            if chain:
                try:
                    result = chain.invoke({"input": question})
                    return {"answer": result.get("answer", "抱歉，我无法回答这个问题。")}
                except Exception as e:
                    logger.error(f"使用知识库生成回答失败: {str(e)}")
                    return {"answer": "生成回答时发生错误，请稍后重试。"}
        
        # 如果没有知识库或RAG链创建失败，使用普通对话
        try:
            chat = ChatOpenAI(model=model, max_tokens=max_length, temperature=temperature)
            prompt = ChatPromptTemplate.from_messages([
                ("system", SYSTEM_PROMPT.format(context="")),
                ("human", "{input}")
            ])
            chain = prompt | chat
            result = chain.invoke({"input": question})
            return {"answer": result.content}
        except Exception as e:
            logger.error(f"生成回答失败: {str(e)}")
            return {"answer": "生成回答时发生错误，请稍后重试。"}

if __name__ == '__main__':
    rag_llm = RagLLM()
    print(rag_llm.invoke('你好，请做个自我介绍。').get('answer'))
