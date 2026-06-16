import argparse
import json
import subprocess
import tkinter as tk


def run_prompt_pipeline(text, submit):
    root = tk.Tk()
    root.title("Qwen Dictation Prompt E2E")
    root.geometry("560x180+120+120")
    root.attributes("-topmost", True)

    tk.Label(root, text="Prompt test field").pack()
    prompt = tk.Text(root, width=64, height=6)
    prompt.pack()
    result = {"content": "", "submitted": False, "automation_error": ""}

    def finish():
        result["content"] = prompt.get("1.0", "end-1c")
        root.destroy()

    def on_return(event):
        result["submitted"] = True
        finish()
        return "break"

    prompt.bind("<Return>", on_return)

    def paste():
        prompt.focus_force()
        root.update()
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        submit_line = "key code 36" if submit else ""
        script = f"""
        tell application "System Events"
            set frontApp to first process whose frontmost is true
            set pasted to false
            try
                click menu item "붙여넣기" of menu "수정" of menu bar 1 of frontApp
                set pasted to true
            end try
            if pasted is false then
                try
                    click menu item "Paste" of menu "Edit" of menu bar 1 of frontApp
                    set pasted to true
                end try
            end if
            if pasted is false then
                keystroke "v" using command down
            end if
            delay 0.12
            {submit_line}
        end tell
        """
        try:
            proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            result["automation_error"] = "osascript timed out; enable Accessibility and Automation permission for the terminal app"
            finish()
            return
        if proc.returncode != 0:
            result["automation_error"] = proc.stderr.strip()
            finish()
        elif not submit:
            root.after(300, finish)

    root.after(600, paste)
    root.after(7000, finish)
    root.mainloop()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="Qwen paste pipeline test")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_prompt_pipeline(args.text, args.submit), ensure_ascii=False))


if __name__ == "__main__":
    main()
