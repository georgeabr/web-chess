#!/usr/bin/env python3
"""
Flask server to connect web chess GUI to Stockfish engine
Ensures difficulty settings (Elo and Skill Level) are applied correctly.
"""

from flask import Flask, request, jsonify, send_file
import subprocess
import os
import random

app = Flask(__name__)

class StockfishEngine:
    def __init__(self, path='/usr/local/bin/stockfish'):
        self.path = path
        self.process = None
        self.start_engine()

    def start_engine(self):
            """Start Stockfish process and ensure old ones are cleared"""
            try:
                # Use -q to keep the killall command quiet
                subprocess.run(['killall', '-9', 'stockfish'], stderr=subprocess.DEVNULL)
            except:
                pass

            self.process = subprocess.Popen(
                [self.path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )

            # Request engine identification
            self._send('uci')

            # Read lines to find the version and wait for uciok
            while True:
                line = self.process.stdout.readline().strip()
                if line.startswith('id name'):
                    # Extracts everything after 'id name '
                    version_info = line[8:]
                    print(f"\n--- Engine Initialised: {version_info} ---")
                if 'uciok' in line:
                    break

    def _send(self, command):
        """Send command to Stockfish with auto-restart logic"""
        try:
            self.process.stdin.write(command + '\n')
            self.process.stdin.flush()
        except:
            self.start_engine()
            self.process.stdin.write(command + '\n')
            self.process.stdin.flush()

    def _wait_for(self, expected):
        """Wait for expected response from engine"""
        while True:
            line = self.process.stdout.readline().strip()
            if expected in line:
                return line

    def get_best_move(self, moves_list, fen='startpos', elo=1500, time_ms=1000, depth=1):
            """Get best move while enforcing difficulty, depth, and MultiPV constraints"""
            self._send('ucinewgame')
            self._send('isready')
            self._wait_for('readyok')

            self._send('setoption name UCI_LimitStrength value true')
            self._send(f'setoption name UCI_Elo value {elo}')

            # Consolidated MultiPV and Skill Level logic to remove redundancy
            if elo <= 100:
                skill_level = 0
                self._send('setoption name MultiPV value 5')
            elif elo <= 500:
                skill_level = 1
                self._send('setoption name MultiPV value 3')
            else:
                # Default to MultiPV 1 for all ratings above 500
                self._send('setoption name MultiPV value 1')
                if elo <= 800:
                    skill_level = 2
                elif elo <= 1100:
                    skill_level = 3
                elif elo <= 1400:
                    skill_level = 4
                elif elo <= 1700:
                    skill_level = 5
                elif elo <= 2100:
                    skill_level = 8
                elif elo <= 2500:
                    skill_level = 9
                else:
                    skill_level = 10

            self._send(f'setoption name Skill Level value {skill_level}')

            self._send('isready')
            self._wait_for('readyok')

            if fen == 'startpos':
                position = 'position startpos'
            else:
                position = f'position fen {fen}'

            if moves_list:
                position += ' moves ' + moves_list

            self._send(position)

            # Execute search with depth and time constraints
            self._send(f'go depth {depth} movetime {time_ms}')

            pv_moves = []
            while True:
                line = self.process.stdout.readline().strip()

                # Extract move choices from MultiPV info lines
                if 'multipv' in line.lower() and 'pv' in line:
                    parts = line.split()
                    try:
                        pv_idx = parts.index('pv')
                        if pv_idx + 1 < len(parts):
                            pv_moves.append(parts[pv_idx + 1])
                    except ValueError:
                        continue

                if line.startswith('bestmove'):
                    # For low Elo, pick a random choice from the non-optimal PV moves
                    if elo <= 500 and len(pv_moves) > 1:
                        return random.choice(pv_moves[1:])

                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
                    return None


    def quit(self):
        """Cleanly shut down the engine process"""
        try:
            self._send('quit')
            self.process.wait(timeout=2)
        except:
            if self.process:
                self.process.terminate()

# Initialize the global engine instance
engine = StockfishEngine()

@app.route('/')
def index():
    """Serve the chess GUI HTML file"""
    return send_file('chess_gui.html')

@app.route('/stockfish', methods=['POST'])
def stockfish_move():
    """Endpoint for the GUI to request a move"""
    data = request.json
    moves = data.get('moves', '')
    fen = data.get('fen', 'startpos')
    difficulty = data.get('difficulty', 1500)
    time_ms = data.get('time_ms', 1000)
    depth = data.get('depth', 1)

    difficulty = max(0, min(3190, difficulty))
    time_ms = max(1, min(10000, time_ms))
    depth = max(1, min(100, depth)) # Ensure depth is within reasonable bounds

    try:
        # Pass the depth parameter to the engine
        best_move = engine.get_best_move(
            moves,
            fen=fen,
            elo=difficulty,
            time_ms=time_ms,
            depth=depth
        )
        return jsonify({'bestmove': best_move})
    except Exception as e:
        print(f"Error communicating with Stockfish: {e}")
        engine.start_engine()
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    """Basic health check"""
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    try:
        print("=" * 60)
        print("Chess vs Stockfish - Web Interface")
        print("=" * 60)
        print("\nStarting server...")
        print("Open your browser and go to: http://localhost:5000")
        print("\nPress Ctrl+C to stop the server")
        print("=" * 60)

        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
    finally:
        engine.quit()
