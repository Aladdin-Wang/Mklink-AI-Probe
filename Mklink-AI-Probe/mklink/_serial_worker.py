"""Private serial I/O worker. stdout is binary RX; stderr is JSON control.

Run as a script in the bundled Python runtime, independently of the UI/GIL.
Only this process opens the port. The caller retains the application port lock.
"""
import base64
import json
import queue
import struct
import sys
import threading

# Executed by filename: do not shadow pyserial with mklink/serial/.
if __package__ in (None, ''):
    sys.path.pop(0)
import serial


def main():
    def reply(value):
        sys.stderr.write(json.dumps(value) + '\n')
        sys.stderr.flush()

    try:
        port = serial.serial_for_url(sys.argv[1], int(sys.argv[2]), timeout=.01, write_timeout=5)
    except Exception as exc:
        reply({'error': str(exc)})
        return
    stopped = threading.Event()
    read_lock = threading.Lock()
    pending = queue.Queue(maxsize=4096)  # at most 16 MiB, then explicit backpressure
    epoch = 0

    def receive():
        try:
            while not stopped.is_set():
                with read_lock:
                    generation = epoch
                    data = port.read(min(4096, port.in_waiting) or 1)
                if data:
                    while not stopped.is_set():
                        try:
                            pending.put((b'D', generation, data), timeout=.05)
                            break
                        except queue.Full:
                            pass
        except Exception as exc:
            if not stopped.is_set():
                pending.put((b'E', epoch, str(exc).encode('utf-8')))

    def transmit():
        try:
            while not stopped.is_set():
                try:
                    kind, generation, data = pending.get(timeout=.05)
                except queue.Empty:
                    continue
                packet = struct.pack('<cII', kind, generation, len(data)) + data
                sys.stdout.buffer.write(packet)
                sys.stdout.buffer.flush()
        except (BrokenPipeError, OSError):
            stopped.set()

    rx = threading.Thread(target=receive, daemon=True)
    tx = threading.Thread(target=transmit, daemon=True)
    rx.start()
    tx.start()
    reply({'ready': True})
    try:
        for line in sys.stdin:
            try:
                command = json.loads(line)
                op = command['op']
                if op == 'write':
                    reply({'result': port.write(base64.b64decode(command['data']))})
                elif op == 'flush':
                    port.flush()
                    reply({'result': None})
                elif op == 'reset_input_buffer':
                    with read_lock:
                        epoch += 1
                        port.reset_input_buffer()
                    reply({'epoch': epoch})
                elif op == 'reset_output_buffer':
                    port.reset_output_buffer()
                    reply({'result': None})
                elif op == 'close':
                    stopped.set()
                    port.cancel_read()
                    rx.join(timeout=1)
                    port.close()
                    reply({'result': None})
                    break
                else:
                    raise ValueError('Unknown serial worker operation')
            except Exception as exc:
                reply({'error': str(exc)})
    finally:
        stopped.set()
        port.close()


if __name__ == '__main__':
    main()
