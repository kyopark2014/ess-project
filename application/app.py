import streamlit as st 
import chat
import json
import os
import mcp_config 
import asyncio
import logging
import sys

from langchain_core.documents import Document

logging.basicConfig(
    level=logging.INFO,  
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("streamlit")

os.environ["DEV"] = "true"  # Skip user confirmation of get_user_input

# title
st.set_page_config(page_title='ESS Agent', page_icon=None, layout="centered", initial_sidebar_state="auto", menu_items=None)

mode_descriptions = {
    "일상적인 대화": [
        "대화이력을 바탕으로 챗봇과 일상의 대화를 편안히 즐길수 있습니다."
    ],
    "RAG": [
        "Bedrock Knowledge Base를 이용해 구현한 RAG로 필요한 정보를 검색합니다."
    ],    
    "Agent": [
        "Strands Agent SDK를 활용한 Agent를 이용합니다."
    ]
}

with st.sidebar:
    st.title("🔮 Menu")
    
    st.markdown(
        "Stands Agent SDK를 이용하여 효율적인 Agent를 구현합니다." 
        "상세한 코드는 [Github](https://github.com/kyopark2014/strands-agent)을 참조하세요."
    )

    st.subheader("🐱 대화 형태")
    
    # radio selection
    mode = st.radio(
        label="원하는 대화 형태를 선택하세요. ",options=['일상적인 대화', 'RAG', 'Agent'], index=2
    )   
    st.info(mode_descriptions[mode][0])    
    # print('mode: ', mode)

    strands_tools = ["calculator", "current_time"]
    mcp_options = [
        "basic", "knowledge base", "tavily-search", "aws document", "use_aws",
        "code interpreter", "filesystem", "trade_info", "사용자 설정"
    ]
    mcp_selections = {}
    default_mcp_selections = ["basic", "tavily-search"]
        
    mcp_selections = {}
    strands_selections = {}
    default_strands_tools = []
        
    if mode=="Agent" or mode=="Agent (Chat)":
        with st.expander("MCP 옵션 선택", expanded=True):
            for option in mcp_options:
                default_value = option in default_mcp_selections
                mcp_selections[option] = st.checkbox(option, key=f"mcp_{option}", value=default_value)
            
        with st.expander("Strands Tools 옵션 선택", expanded=True):            
            for option in strands_tools:
                default_value = option in default_strands_tools
                strands_selections[option] = st.checkbox(option, key=f"strands_{option}", value=default_value)
        
        if mcp_selections["사용자 설정"]:
            mcp = {}
            try:
                with open("user_defined_mcp.json", "r", encoding="utf-8") as f:
                    mcp = json.load(f)
                    logger.info(f"loaded user defined mcp: {mcp}")
            except FileNotFoundError:
                logger.info("user_defined_mcp.json not found")
                pass
            
            mcp_json_str = json.dumps(mcp, ensure_ascii=False, indent=2) if mcp else ""
            
            mcp_info = st.text_area(
                "MCP 설정을 JSON 형식으로 입력하세요",
                value=mcp_json_str,
                height=150
            )
            logger.info(f"mcp_info: {mcp_info}")

            if mcp_info:
                try:
                    mcp_config.mcp_user_config = json.loads(mcp_info)
                    logger.info(f"mcp_user_config: {mcp_config.mcp_user_config}")                    
                    st.success("JSON 설정이 성공적으로 로드되었습니다.")                    
                except json.JSONDecodeError as e:
                    st.error(f"JSON 파싱 오류: {str(e)}")
                    st.error("올바른 JSON 형식으로 입력해주세요.")
                    logger.error(f"JSON 파싱 오류: {str(e)}")
                    mcp_config.mcp_user_config = {}
            else:
                mcp_config.mcp_user_config = {}
                    
            with open("user_defined_mcp.json", "w", encoding="utf-8") as f:
                json.dump(mcp_config.mcp_user_config, f, ensure_ascii=False, indent=4)
            logger.info("save to user_defined_mcp.json")

    # model selection box
    modelName = st.selectbox(
        '🖊️ 사용 모델을 선택하세요',
        (
            "Claude 4.5 Haiku",
            "Claude 4.5 Sonnet",
            "Claude 4.5 Opus",  
            "Claude 4 Opus", 
            "Claude 4 Sonnet", 
            "Claude 3.7 Sonnet", 
            "Claude 3.5 Sonnet", 
            "Claude 3.0 Sonnet", 
            "Claude 3.5 Haiku", 
            "OpenAI OSS 120B",
            "OpenAI OSS 20B",
            "Nova 2 Lite",
            "Nova Premier", 
            "Nova Pro", 
            "Nova Lite", 
            "Nova Micro",            
        ), index=4
    )

    # debug checkbox
    select_debugMode = st.checkbox('Debug Mode', value=True)
    debugMode = 'Enable' if select_debugMode else 'Disable'
    
    # extended thinking of claude 3.7 sonnet
    reasoningMode = 'Disable'
    if modelName == 'Claude 3.7 Sonnet' or modelName == 'Claude 4 Sonnet' or modelName == 'Claude 4 Opus' or modelName == 'Claude 4.5 Sonnet' or modelName == 'Claude 4.5 Haiku':
        select_reasoning = st.checkbox('Reasoning', value=False)
        reasoningMode = 'Enable' if select_reasoning else 'Disable'

    uploaded_file = None
    if mode=="RAG" or mode=="Agent":
        st.subheader("📋 문서 업로드")
        uploaded_file = st.file_uploader("RAG를 위한 파일을 선택합니다.", type=["pdf", "txt", "py", "md", "csv", "json"], key=chat.fileId)
    
    selected_strands_tools = [tool for tool, is_selected in strands_selections.items() if is_selected]
    selected_mcp_servers = [server for server, is_selected in mcp_selections.items() if is_selected]
    
    chat.update(modelName, reasoningMode, debugMode)

    st.success(f"Connected to {modelName}", icon="💚")
    clear_button = st.button("대화 초기화", key="clear")
    # print('clear_button: ', clear_button)

st.title('🔮 '+ mode)  

if clear_button==True:
    chat.initiate()

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.greetings = False

# Display chat messages from history on app rerun
def display_chat_messages():
    """Print message history
    @returns None
    """
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "images" in message:                
                for url in message["images"]:
                    logger.info(f"url: {url}")

                    file_name = url[url.rfind('/')+1:]
                    st.image(url, caption=file_name, use_container_width=True)            

display_chat_messages()

# Greet user
if not st.session_state.greetings:
    with st.chat_message("assistant"):
        intro = "아마존 베드락을 이용하여 주셔서 감사합니다. 편안한 대화를 즐기실수 있으며, 파일을 업로드하면 요약을 할 수 있습니다."
        st.markdown(intro)
        # Add assistant response to chat history
        st.session_state.messages.append({"role": "assistant", "content": intro})
        st.session_state.greetings = True

if clear_button or "messages" not in st.session_state:
    st.session_state.messages = []     
    uploaded_file = None   
    
    st.session_state.greetings = False

file_name = ""
if uploaded_file is not None and clear_button==False:
    logger.info(f"uploaded_file.name: {uploaded_file.name}")
    if uploaded_file.name:
        logger.info(f"csv type? {uploaded_file.name.lower().endswith(('.csv'))}")

    if uploaded_file.name:
        chat.initiate()

        if debugMode=='Enable':
            status = '선택한 파일을 업로드합니다.'
            logger.info(f"status: {status}")
            st.info(status)

        file_name = uploaded_file.name
        logger.info(f"uploading... file_name: {file_name}")
        file_url = chat.upload_to_s3(uploaded_file.getvalue(), file_name)
        logger.info(f"file_url: {file_url}")

        import utils
        utils.sync_data_source()  # sync uploaded files
            
        status = f'선택한 "{file_name}"의 내용을 요약합니다.'
        if debugMode=='Enable':
            logger.info(f"status: {status}")
            st.info(status)
    
        msg = chat.get_summary_of_uploaded_file(file_name, st)
        st.session_state.messages.append({"role": "assistant", "content": f"선택한 문서({file_name})를 요약하면 아래와 같습니다.\n\n{msg}"})    
        logger.info(f"msg: {msg}")

        st.write(msg)

# Always show the chat input
if prompt := st.chat_input("메시지를 입력하세요."):
    with st.chat_message("user"):  # display user message in chat message container
        st.markdown(prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})  # add user message to chat history
    prompt = prompt.replace('"', "").replace("'", "")
    logger.info(f"prompt: {prompt}")
    #logger.info(f"is_updated: {agent.is_updated}")

    with st.chat_message("assistant"):
        image_urls = []

        if mode == '일상적인 대화':
            stream = chat.general_conversation(prompt)            
            response = st.write_stream(stream)
            logger.info(f"response: {response}")

            chat.save_chat_history(prompt, response)

        elif mode == 'RAG':            
            # knowlege base retrieval
            response = chat.run_rag_with_knowledge_base(prompt, st)        

            st.markdown(response)

            # retrieve and generate
            # containers = {
            #     "notification": [st.empty() for _ in range(1000)],
            #     "message": st.empty()
            # }
            # response = chat.run_rag_using_retrieve_and_generate(prompt, containers)
                        
            logger.info(f"response: {response}")
            chat.save_chat_history(prompt, response)

        elif mode == 'Agent':
            with st.status("thinking...", expanded=True, state="running") as status:
                containers = {
                    "tools": st.empty(),
                    "status": st.empty(),
                    "notification": [st.empty() for _ in range(1000)],
                    "key": st.empty()
                }

                response, image_urls = asyncio.run(chat.run_strands_agent(
                    query=prompt, 
                    strands_tools=selected_strands_tools, 
                    mcp_servers=selected_mcp_servers,
                    containers=containers))

        if chat.debug_mode == 'Disable':
           st.markdown(response)
        
        for url in image_urls:
            logger.info(f"url: {url}")
            file_name = url[url.rfind('/')+1:]
            st.image(url, caption=file_name, use_container_width=True)      

        st.session_state.messages.append({
            "role": "assistant", 
            "content": response,
            "images": image_urls if image_urls else []
        })
    
    

