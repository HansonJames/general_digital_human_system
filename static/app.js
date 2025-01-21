var SpeechSDK;
var peerConnection;
var cogSvcRegin;
var subscriptionKey;
var currentAvatarSynthesizer;
var isRecording = false;

var speakerHandel = function (avatarSynthesizer, msg, qingxu) {
    var timbre = document.getElementById("voiceSelect").value;
    var spokenSsml = `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='zh-CN'>
    <voice name='${timbre}'>
        <mstts:express-as style='${qingxu}' role='YoungAdultFemale' styledegreee='2'>${msg}</mstts:express-as>
    </voice></speak>`;

    avatarSynthesizer.speakSsmlAsync(spokenSsml).then((r) => {
        if (r.reason === SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
            console.log("语音合成完成");
        } else {
            console.log("语音合成失败: " + r.errorDetails);
        }
    }).catch((e) => {
        console.error("语音合成错误: ", e);
        avatarSynthesizer.close();
    });
}

var chatWithAI = function (avatarSynthesizer) {
    var chatInput = document.getElementById("chatInput");
    var chatText = chatInput.value.trim();
    if (!chatText) return;

    // 添加发送按钮动画效果
    const sendButton = document.querySelector('#userSendArea button:last-child');
    sendButton.style.transform = 'scale(0.95)';
    sendButton.style.backgroundColor = '#e0e0e0';
    setTimeout(() => {
        sendButton.style.transform = '';
        sendButton.style.backgroundColor = '';
    }, 200);

    console.log("发送问题：" + chatText);
    chatInput.value = ""; // 立即清空输入框
    chatInput.focus();
    
    var xhr = new XMLHttpRequest();
    xhr.open("POST", `http://127.0.0.1:8000/chat?query=${encodeURIComponent(chatText)}&knowledge=${encodeURIComponent(window.selectedKnowledge || "")}`);
    xhr.addEventListener("readystatechange", function () {
        if (this.readyState === 4) {
            if (this.status === 200) {
                var responseData = JSON.parse(this.responseText);
                console.log("收到回答：", responseData);
                speakerHandel(avatarSynthesizer, responseData[0].msg, responseData[0].qingxu);
                var responseArea = document.getElementById("responseArea");
                
                // 添加用户消息
                var userMessage = document.createElement('div');
                userMessage.className = 'message user-message';
                userMessage.textContent = chatText;
                responseArea.appendChild(userMessage);
                
                // 添加机器人消息
                var botMessage = document.createElement('div');
                botMessage.className = 'message bot-message';
                botMessage.textContent = responseData[0].msg;
                responseArea.appendChild(botMessage);
                
                // 滚动到底部
                responseArea.scrollTop = responseArea.scrollHeight;
            } else {
                console.error("请求失败：", this.status);
            }
        }
    });
    xhr.send();
}

async function initializeApp() {
    try {
        // 1. 获取配置
        const configResponse = await fetch('/api/config');
        const config = await configResponse.json();
        cogSvcRegin = config.cogSvcRegin;
        subscriptionKey = config.subscriptionKey;
        console.log("配置信息已加载");

        // 2. 初始化语音配置
        const speechConfig = SpeechSDK.SpeechConfig.fromSubscription(subscriptionKey, cogSvcRegin);
        speechConfig.speechSynthesisVoiceName = "zh-CN-XiaochenMultilingualNeural";
        speechConfig.speechSynthesisLanguage = "zh-CN";
        const videoFormat = new SpeechSDK.AvatarVideoFormat();

        // 3. 获取虚拟形象配置
        const avatarsResponse = await fetch('/api/avatars');
        const avatars = await avatarsResponse.json();
        const defaultAvatar = avatars.find(a => a.character === "Lori") || avatars[0];
        const avatarConfig = new SpeechSDK.AvatarConfig(
            defaultAvatar.character,
            defaultAvatar.style,
            videoFormat
        );

        async function setupWebRTC() {
            // 获取WebRTC连接信息
            const response = await fetch(
                `https://${cogSvcRegin}.tts.speech.microsoft.com/cognitiveservices/avatar/relay/token/v1`,
                {
                    headers: {
                        'Ocp-Apim-Subscription-Key': subscriptionKey
                    }
                }
            );
            const responseData = await response.json();

            // 创建WebRTC连接
            peerConnection = new RTCPeerConnection({
                iceServers: [{
                    urls: [responseData.Urls[0]],
                    username: responseData.Username,
                    credential: responseData.Password
                }]
            });

            // 设置WebRTC事件处理
            peerConnection.ontrack = function (event) {
                if (event.track.kind === "video") {
                    console.log("视频轨道已接收");
                    var videoElement = document.createElement(event.track.kind);
                    videoElement.srcObject = event.streams[0];
                    videoElement.autoplay = true;
                    videoElement.id = "videoPlayer";
                    videoElement.muted = false;
                    videoElement.playsInline = true;
                    
                    // 将视频元素插入到video-container中
                    const videoContainer = document.querySelector('.video-container');
                    if (videoContainer) {
                        // 移除现有的视频元素（如果有）
                        const existingVideo = videoContainer.querySelector('video');
                        if (existingVideo) {
                            existingVideo.remove();
                        }
                        videoContainer.appendChild(videoElement);
                    }
                }

                if (event.track.kind === "audio") {
                    console.log("音频轨道已接收");
                    var audioElement = document.createElement(event.track.kind);
                    audioElement.srcObject = event.streams[0];
                    audioElement.autoplay = true;
                    audioElement.id = "audioPlayer";
                    audioElement.muted = false;
                    document.body.appendChild(audioElement);
                }
            };

            peerConnection.oniceconnectionstatechange = function () {
                console.log("连接状态：" + peerConnection.iceConnectionState);
                if (peerConnection.iceConnectionState === 'disconnected' || 
                    peerConnection.iceConnectionState === 'failed') {
                    console.log("尝试重新连接...");
                    setupWebRTC().catch(console.error);
                }
            };

            // 添加音视频流
            peerConnection.addTransceiver("video", {direction: "sendrecv"});
            peerConnection.addTransceiver("audio", {direction: "sendrecv"});

            return peerConnection;
        }

        // 初始化WebRTC
        await setupWebRTC();

        // 创建并启动虚拟形象合成器
        currentAvatarSynthesizer = new SpeechSDK.AvatarSynthesizer(speechConfig, avatarConfig);
        await currentAvatarSynthesizer.startAvatarAsync(peerConnection);
        console.log("虚拟形象已启动");

        // 初始化语音识别
        let recognizer;

        async function initializeSpeechRecognition() {
            try {
                // 获取语音配置
                const response = await fetch('/api/speech-config');
                const config = await response.json();
                
                // 创建语音配置
                const speechConfig = SpeechSDK.SpeechConfig.fromSubscription(
                    config.subscriptionKey,
                    config.region
                );
                speechConfig.speechRecognitionLanguage = config.language;

                // 请求麦克风权限
                await navigator.mediaDevices.getUserMedia({ audio: true });
                
                // 创建音频配置
                const audioConfig = SpeechSDK.AudioConfig.fromDefaultMicrophoneInput();
                
                // 创建识别器
                recognizer = new SpeechSDK.SpeechRecognizer(speechConfig, audioConfig);
                
                // 设置识别结果处理
                recognizer.recognized = (s, e) => {
                    if (e.result.reason === SpeechSDK.ResultReason.RecognizedSpeech) {
                        chatInput.value = e.result.text;
                        stopRecording();
                        chatInput.focus(); // 聚焦到输入框
                        if (chatInput.value.trim()) {
                            chatWithAI(currentAvatarSynthesizer);
                        }
                    }
                };

                console.log("语音识别初始化成功");
            } catch (error) {
                console.error("语音识别初始化失败:", error);
            }
        }

        // 开始录音
        function startRecording() {
            if (!recognizer || isRecording) return;
            
            isRecording = true;
            const voiceInputBtn = document.querySelector('.input-container button');
            voiceInputBtn.innerHTML = "⏺️";
            voiceInputBtn.classList.add('recording');
            recognizer.startContinuousRecognitionAsync();
        }

        // 停止录音
        function stopRecording() {
            if (!recognizer || !isRecording) return;
            
            recognizer.stopContinuousRecognitionAsync();
            isRecording = false;
            const voiceInputBtn = document.querySelector('.input-container button');
            voiceInputBtn.innerHTML = "🎤";
            voiceInputBtn.classList.remove('recording');
        }

        // 语音输入按钮事件
        document.querySelector('.input-container button').addEventListener("click", function() {
            if (isRecording) {
                stopRecording();
            } else {
                startRecording();
            }
        });

        // 页面加载时初始化语音识别
        initializeSpeechRecognition();

        // 加载知识库列表
        async function loadKnowledgeBases() {
            try {
                const response = await fetch('/api/knowledge-bases');
                const data = await response.json();
                const select = document.getElementById('knowledgeSelect');
                select.innerHTML = '<option value="">选择知识库</option>';
                data.forEach(file => {
                    const option = document.createElement('option');
                    option.value = file;
                    option.text = file;
                    select.appendChild(option);
                });
                // 设置默认选中的知识库
                window.selectedKnowledge = select.value;
            } catch (error) {
                console.error('加载知识库列表失败:', error);
            }
        }

        // 检查向量化进度
        async function checkVectorizationProgress() {
            try {
                const response = await fetch('/api/vectorization-progress');
                const data = await response.json();
                
                const progressBar = document.querySelector('.progress-bar');
                const progressElement = progressBar.querySelector('.progress');
                const statusElement = document.querySelector('.progress-status');
                
                if (data.status === 'processing') {
                    progressBar.style.display = 'block';
                    statusElement.style.display = 'block';
                    progressElement.style.width = `${data.percentage}%`;
                    statusElement.textContent = `正在处理: ${data.file} (${Math.round(data.percentage)}%)`;
                    setTimeout(checkVectorizationProgress, 1000);
                } else if (data.status === 'completed') {
                    progressBar.style.display = 'none';
                    statusElement.style.display = 'none';
                    loadKnowledgeBases();
                } else if (data.status === 'error') {
                    progressBar.style.display = 'none';
                    statusElement.style.display = 'block';
                    statusElement.textContent = `处理失败: ${data.error}`;
                    setTimeout(() => {
                        statusElement.style.display = 'none';
                    }, 3000);
                }
            } catch (error) {
                console.error('检查向量化进度失败:', error);
            }
        }

        // 处理文件上传
        document.getElementById('fileInput').addEventListener('change', async function(e) {
            if (!this.files.length) return;
            
            const file = this.files[0];
            const formData = new FormData();
            formData.append('file', file);

            try {
                const progressBar = document.querySelector('.progress-bar');
                const progressElement = progressBar.querySelector('.progress');
                const statusElement = document.querySelector('.progress-status');
                
                progressBar.style.display = 'block';
                statusElement.style.display = 'block';
                progressElement.style.width = '0%';
                statusElement.textContent = '正在上传文件...';

                const response = await fetch('/api/upload-document', {
                    method: 'POST',
                    body: formData
                });
                
                if (response.ok) {
                    checkVectorizationProgress();
                } else {
                    const error = await response.json();
                    progressBar.style.display = 'none';
                    statusElement.textContent = `上传失败: ${error.error}`;
                    setTimeout(() => {
                        statusElement.style.display = 'none';
                    }, 3000);
                }
            } catch (error) {
                console.error('上传文档失败:', error);
                const statusElement = document.querySelector('.progress-status');
                statusElement.style.display = 'block';
                statusElement.textContent = '上传失败，请重试';
                setTimeout(() => {
                    statusElement.style.display = 'none';
                }, 3000);
            }
        });

        // 知识库选择事件
        document.getElementById('knowledgeSelect').addEventListener('change', function() {
            window.selectedKnowledge = this.value;
        });

        // 异步加载虚拟形象
        let isChangingAvatar = false;
        let retryCount = 0;
        const MAX_RETRIES = 3;

        async function changeAvatar(selectedAvatar) {
            if (isChangingAvatar) return;
            
            try {
                isChangingAvatar = true;
                document.getElementById("loading").style.display = "block";
                
                // 关闭当前连接
                if (currentAvatarSynthesizer) {
                    currentAvatarSynthesizer.close();
                }

                // 移除现有的视频和音频元素
                const videoPlayer = document.getElementById("videoPlayer");
                const audioPlayer = document.getElementById("audioPlayer");
                if (videoPlayer) videoPlayer.remove();
                if (audioPlayer) audioPlayer.remove();

                // 等待连接完全关闭
                await new Promise(resolve => setTimeout(resolve, 2000));

                // 重新设置WebRTC连接
                await setupWebRTC();

                // 创建新的虚拟形象配置
                const newAvatarConfig = new SpeechSDK.AvatarConfig(
                    selectedAvatar.character,
                    selectedAvatar.style,
                    videoFormat
                );

                // 创建新的合成器
                currentAvatarSynthesizer = new SpeechSDK.AvatarSynthesizer(speechConfig, newAvatarConfig);
                
                // 设置超时
                const timeoutPromise = new Promise((_, reject) => {
                    setTimeout(() => reject(new Error('切换超时')), 15000);
                });

                // 等待启动完成或超时
                await Promise.race([
                    currentAvatarSynthesizer.startAvatarAsync(peerConnection),
                    timeoutPromise
                ]);

                // 重置重试计数
                retryCount = 0;

            } catch (error) {
                console.error('切换虚拟形象失败:', error);
                
                if (retryCount < MAX_RETRIES) {
                    retryCount++;
                    console.log(`重试第 ${retryCount} 次`);
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    return changeAvatar(selectedAvatar);
                } else {
                    alert('切换虚拟形象失败，请刷新页面重试');
                    location.reload();
                }
            } finally {
                isChangingAvatar = false;
                document.getElementById("loading").style.display = "none";
            }
        }

        document.getElementById('avatarSelect').addEventListener("change", function() {
            const selectedAvatar = JSON.parse(this.value);
            changeAvatar(selectedAvatar);
        });

        // 初始加载知识库列表
        loadKnowledgeBases();

        // 发送消息的统一处理函数
        function sendMessage() {
            if (!isRecording) {
                const videoPlayer = document.getElementById("videoPlayer");
                const audioPlayer = document.getElementById("audioPlayer");
                if (videoPlayer) videoPlayer.muted = false;
                if (audioPlayer) audioPlayer.muted = false;
                if (videoPlayer) videoPlayer.play();
                if (audioPlayer) audioPlayer.play();
                chatWithAI(currentAvatarSynthesizer);
            }
        }

        // 创建并添加发送按钮
        const sendButton = document.createElement("button");
        sendButton.innerHTML = "发送";
        sendButton.style.width = "80px";
        sendButton.id = "sendButton";

        // 获取userSendArea
        const userSendArea = document.getElementById('userSendArea');
        if (userSendArea) {
            // 移除旧的发送按钮
            const oldSendButton = document.getElementById('sendButton');
            if (oldSendButton) {
                oldSendButton.remove();
            }
            // 添加新的发送按钮
            userSendArea.appendChild(sendButton);
        }

        // 发送按钮事件
        sendButton.addEventListener("click", function () {
            console.log("send button clicked");
            const videoPlayer = document.getElementById("videoPlayer");
            const audioPlayer = document.getElementById("audioPlayer");
            if (videoPlayer) videoPlayer.muted = false;
            if (audioPlayer) audioPlayer.muted = false;
            if (videoPlayer) videoPlayer.play();
            if (audioPlayer) audioPlayer.play();
            chatWithAI(currentAvatarSynthesizer);
        });

        // 回车键发送
        document.getElementById('chatInput').addEventListener("keypress", function(event) {
            if (event.key === "Enter" && !event.shiftKey && !isRecording) {
                event.preventDefault();
                sendMessage();
            }
        });

        // 初始聚焦到输入框
        document.getElementById('chatInput').focus();

    } catch (error) {
        console.error('初始化失败:', error);
        alert('系统初始化失败，请刷新页面重试');
    }
}

// 等待DOM加载完成后初始化
document.addEventListener("DOMContentLoaded", function () {
    if (!!window.SpeechSDK) {
        SpeechSDK = window.SpeechSDK;
        initializeApp().catch(console.error);
    }
});
