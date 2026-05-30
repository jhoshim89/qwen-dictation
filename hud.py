import tkinter as tk
import time
import sys
import argparse
import audio_level

class FloatingHUD:
    def __init__(self, max_time=30):
        self.max_time = max_time
        self.start_time = time.time()
        self.root = tk.Tk()
        
        # Configure window styles for premium floating overlay
        self.root.overrideredirect(True) # Remove title bar and window frame
        self.root.attributes("-topmost", True) # Stay on top of all windows
        self.root.attributes("-alpha", 0.92) # Sleek transparency
        self.root.configure(bg="#0b0f19")
        
        # Determine geometry (Top Center of the screen, just below menu bar)
        screen_width = self.root.winfo_screenwidth()
        w = 300
        h = 42
        x = (screen_width - w) // 2
        y = 60 # Float elegantly just below the top menu bar/notch
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        
        # Rounded window effect (borderless canvas or frame container)
        self.frame = tk.Frame(self.root, bg="#0b0f19", highlightthickness=1, highlightbackground="#312e81", bd=0)
        self.frame.pack(fill="both", expand=True)
        
        # Red pulsing dot indicator
        self.dot_label = tk.Label(self.frame, text="🔴", font=("Arial", 12), bg="#0b0f19", fg="#ef4444")
        self.dot_label.pack(side="left", padx=(15, 5))
        
        # Text label (Listening...)
        self.text_label = tk.Label(self.frame, text="로컬 받아쓰기 중", font=("Plus Jakarta Sans", 11, "bold"), bg="#0b0f19", fg="#f3f4f6")
        self.text_label.pack(side="left", padx=5)

        # Live mic level meter (fills based on speaking volume)
        self.meter_w = 70
        self.meter_h = 10
        self.meter = tk.Canvas(self.frame, width=self.meter_w, height=self.meter_h,
                               bg="#1e293b", highlightthickness=0)
        self.meter.pack(side="left", padx=6)
        self.meter_fill = self.meter.create_rectangle(0, 0, 0, self.meter_h,
                                                      fill="#22c55e", width=0)

        # Time elapsed counter
        self.time_label = tk.Label(self.frame, text="00:00", font=("Plus Jakarta Sans", 11, "bold"), bg="#0b0f19", fg="#a5b4fc")
        self.time_label.pack(side="right", padx=(5, 15))
        
        self.blink_state = True
        self.update_loop()
        
    def update_loop(self):
        elapsed = int(time.time() - self.start_time)
        
        # Check for timeout
        if elapsed >= self.max_time:
            self.root.destroy()
            sys.exit(0)
            
        # Format time
        mins, secs = divmod(elapsed, 60)
        self.time_label.config(text=f"{mins:02d}:{secs:02d}")
        
        # Blink the red dot for recording feel
        self.blink_state = not self.blink_state
        dot_color = "#ef4444" if self.blink_state else "#1e293b"
        self.dot_label.config(fg=dot_color)

        # Update mic level meter bar from the level file
        level = audio_level.read_level()
        fill_w = int(self.meter_w * max(0.0, min(1.0, level)))
        # 음량이 클수록 초록->노랑->빨강
        if level < 0.5:
            color = "#22c55e"
        elif level < 0.8:
            color = "#eab308"
        else:
            color = "#ef4444"
        self.meter.coords(self.meter_fill, 0, 0, fill_w, self.meter_h)
        self.meter.itemconfig(self.meter_fill, fill=color)

        # Schedule next update in 500ms
        self.root.after(500, self.update_loop)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--max_time', type=int, default=30)
    args = parser.parse_args()
    
    hud = FloatingHUD(max_time=args.max_time)
    hud.root.mainloop()
