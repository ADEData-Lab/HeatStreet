"""
Quick script to monitor memory usage of the pipeline.
Run this in a separate terminal while the pipeline is running.
"""
import psutil
import time
from datetime import datetime

def format_bytes(bytes):
    """Format bytes to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024.0:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.1f} TB"

def monitor_process(process_name="python.exe", interval=5):
    """Monitor memory usage of a process."""
    print(f"Monitoring {process_name} every {interval} seconds...")
    print(f"{'Time':<20} {'PID':<10} {'RSS':<15} {'VMS':<15} {'CPU%':<10}")
    print("-" * 70)

    peak_rss = 0

    try:
        while True:
            found = False
            for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
                try:
                    if process_name.lower() in proc.info['name'].lower():
                        # Check if it's running run_analysis.py
                        try:
                            cmdline = proc.cmdline()
                            if 'run_analysis.py' in ' '.join(cmdline):
                                found = True
                                mem_info = proc.info['memory_info']
                                rss = mem_info.rss
                                vms = mem_info.vms
                                cpu = proc.cpu_percent(interval=0.1)

                                peak_rss = max(peak_rss, rss)

                                timestamp = datetime.now().strftime("%H:%M:%S")
                                print(f"{timestamp:<20} {proc.info['pid']:<10} "
                                      f"{format_bytes(rss):<15} {format_bytes(vms):<15} {cpu:<10.1f}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if not found:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for pipeline to start...")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n" + "="*70)
        print(f"Peak RSS: {format_bytes(peak_rss)}")
        print("Monitoring stopped.")

if __name__ == "__main__":
    monitor_process()
