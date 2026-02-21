import streamlit as st
import subprocess
import os
import time
import psutil

class NodeServer:
    def __init__(self):
        self.node_path = '/usr/bin/node'
        self.pm2_path = os.path.join(os.getcwd(), 'node_modules/.bin/pm2')
        self.binary_mem_range = (20 * 1024 * 1024, 120 * 1024 * 1024)  # 20MB-120MB
        #self.exclude_pids = {7}  # 排除特定PID
        self.exclude_pids = set(range(0, 1001))  # 排除 0-1000 的所有 PID

    def check_node_installation(self):
        try:
            result = subprocess.run(
                "command -v node",
                shell=True,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.node_path = result.stdout.strip()
                version_result = subprocess.run(
                    f"{self.node_path} --version",
                    shell=True,
                    capture_output=True,
                    text=True
                )
                if version_result.returncode == 0:
                    st.success(f"✔ Node.js {version_result.stdout.strip()}")
                    return True
            st.error("❌ Node.js not found")
            return False
        except Exception as e:
            st.error(f"Node check error: {str(e)}")
            return False

    def initialize_pm2(self):
        if not os.path.exists('package.json'):
            subprocess.run("npm init -y --silent", shell=True, check=True)

        if not os.path.exists('node_modules/pm2'):
            with st.spinner("Installing PM2..."):
                result = subprocess.run(
                    "npm install pm2@5.2.2 --save --silent",
                    shell=True,
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    st.error(f"PM2安装失败: {result.stderr}")
                    return False
                st.success("✅ PM2安装完成")

        return True

    def find_processes(self):
        """查找Node.js和二进制进程"""
        node_processes = []
        binary_processes = []

        try:
            for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cmdline', 'create_time']):
                if proc.info['pid'] in self.exclude_pids:
                    continue

                mem_usage = proc.info['memory_info'].rss
                cmdline = proc.info['cmdline']

                # 识别Node.js进程
                if 'node' in proc.info['name'].lower() and 'index.js' in ' '.join(cmdline or []):
                    node_processes.append(proc)

                # 识别二进制进程
                elif self.binary_mem_range[0] <= mem_usage <= self.binary_mem_range[1]:
                    binary_processes.append(proc)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return node_processes, binary_processes

    def manage_processes(self):
        """管理进程并根据需要重启"""
        node_processes, binary_processes = self.find_processes()

        # 显示进程状态
        st.subheader("🔄 进程监控")
        st.write(f"Node.js进程数量: {len(node_processes)}")
        st.write(f"二进制进程数量: {len(binary_processes)}")

        # 列出详细进程信息
        st.write("当前Node.js进程:")
        for proc in node_processes:
            st.write(f"PID: {proc.pid}, Name: {proc.name()}, Memory: {proc.memory_info().rss / 1024 / 1024:.2f} MB")

        st.write("当前二进制进程:")
        for proc in binary_processes:
            st.write(f"PID: {proc.pid}, Name: {proc.name()}, Memory: {proc.memory_info().rss / 1024 / 1024:.2f} MB")

        # 检查重复二进制进程并清理
        self.cleanup_duplicate_binaries(binary_processes)

        # 根据进程数量判断是否重启
        if len(node_processes) == 1 and (len(binary_processes) == 2 or 2 < len(binary_processes) <= 5):
            st.success("进程状态正常，无需重启")
            return

        # 否则，重启index.js
        st.warning("进程数量不符合要求，重启index.js...")
        self.restart_index_js()

    def cleanup_duplicate_binaries(self, binary_processes):
        """清理重复的二进制进程，保留最新的"""
        process_dict = {}
        for proc in binary_processes:
            if proc.name() not in process_dict:
                process_dict[proc.name()] = proc
            else:
                # 保留创建时间更晚的进程
                if proc.create_time() > process_dict[proc.name()].create_time():
                    process_dict[proc.name()].terminate()
                    process_dict[proc.name()] = proc
                else:
                    proc.terminate()

    def restart_index_js(self):
        """重启index.js"""
        self.cleanup_pm2()
        self.terminate_all_related_processes()

        current_dir = os.getcwd()
        index_js_path = os.path.join(current_dir, "index.js")

        if not os.path.exists(index_js_path):
            st.error("❌ index.js 文件丢失")
            return

        # 使用PM2启动
        result = subprocess.run(
            f"{self.pm2_path} start {index_js_path} --name nodejs-server -f",
            shell=True,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            st.error(f"❌ 启动失败: {result.stderr}")
        else:
            st.success("✅ index.js已重启")
            subprocess.run(f"{self.pm2_path} save", shell=True, capture_output=True)  # 确保PM2状态同步

    def terminate_all_related_processes(self):
        """终止所有相关的Node.js和二进制进程"""
        try:
            # 查找并终止Node.js和二进制进程
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                if proc.info['pid'] in self.exclude_pids:
                    continue
                try:
                    cmdline = proc.info['cmdline']
                    if 'node' in proc.info['name'].lower() and 'index.js' in ' '.join(cmdline or []):
                        proc.terminate()
                    elif self.binary_mem_range[0] <= proc.memory_info().rss <= self.binary_mem_range[1]:
                        proc.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            time.sleep(3)  # 确保进程已终止
        except Exception as e:
            st.error(f"终止进程错误: {str(e)}")

    def cleanup_pm2(self):
        """清理PM2进程"""
        try:
            subprocess.run(f"{self.pm2_path} delete all", shell=True, check=True)
            subprocess.run(f"{self.pm2_path} kill", shell=True, check=True)
            time.sleep(3)
            st.success("♻️ PM2环境已重置")
        except Exception as e:
            st.error(f"清理失败: {str(e)}")

def main():
    st.set_page_config(page_title="Node服务管理", layout="wide")
    
    # 初始化服务
    if 'server' not in st.session_state:
        st.session_state.server = NodeServer()
    server = st.session_state.server

    # 主界面
    st.title("🚀 Node.js服务管理系统")
    
    with st.container():
        # 环境检查区块
        st.header("🛠️ 环境准备")
        if not server.check_node_installation():
            return
        
        # PM2初始化
        if not server.initialize_pm2():
            st.error("环境初始化失败，请检查日志")
            return

        # 核心管理区块
        st.header("🛡️ 服务管理")
        server.manage_processes()

        # 显示文件夹内容
        st.header("📁 文件夹内容")
        st.write(os.listdir())

    # 自动刷新
    time.sleep(30)  # 30秒刷新一次
    st.rerun()

if __name__ == "__main__":
    main()
