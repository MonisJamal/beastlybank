"""
Gradio Web Interface and 24/7 Bot Launcher for Hugging Face Spaces.
"""
import os
import sys
import subprocess
import gradio as gr

# Start the BeastlyBank Discord bot as a persistent background process
bot_process = subprocess.Popen([sys.executable, "bot.py"])

def get_status():
    if bot_process.poll() is None:
        return "🟢 BeastlyBank is Online & Guarding BeastlyFC Finances 24/7!"
    return f"🔴 Bot process stopped with exit code: {bot_process.poll()}"

with gr.Blocks(title="BeastlyBank Status") as demo:
    gr.Markdown(
        """
        # ⚽ BeastlyBank Cloud Controller
        ### Automated Discord Banking & Club Treasury System for BeastlyFC
        """
    )
    status_display = gr.Textbox(value=get_status, label="System Status", interactive=False)
    refresh_button = gr.Button("🔄 Check Live Status")
    refresh_button.click(fn=get_status, outputs=status_display)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
