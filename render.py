# Temporary Handler for render.py

import os
import sys
import logging
import argparse
import subprocess
import datetime
from direct.Showbase.ShowBase import ShowBase
from panda3d.core import WindowProperties, loadPrcFileData

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RenderApp(ShowBase):
    def __init__(self, args):
        # Configure Panda3D settings
        loadPrcFileData('', 'window-type offscreen')
        loadPrcFileData('', 'audio-library-name null')
        loadPrcFileData('', 'framebuffer-multisample 1')
        loadPrcFileData('', 'multisamples 4')

        super().__init__()

        # Set window properties
        props = WindowProperties()
        props.setSize(args.width, args.height)
        self.win.requestProperties(props)

        # Load the model
        self.model = self.loader.loadModel(args.model)
        self.model.reparentTo(self.render)

        # Set camera position
        self.camera.setPos(0, -10, 0)
        self.camera.lookAt(0, 0, 0)

        # Render and save the image
        self.taskMgr.add(self.render_task, "RenderTask")
        self.output_path = args.output

    def render_task(self, task):
        # Render the scene to a texture
        tex = self.win.getScreenshot()
        tex.write(self.output_path)
        
        logging.info(f"Rendered image saved to {self.output_path}")
        # Set up a green background
        self.setBackgroundColor(0, 1, 0, 1) # RGB A: Green
        # Exit the application
        sys.exit(0)
def main():
    render = RenderApp()
    parser = argparse.ArgumentParser(description="Render a 3D model to an image.")
    parser.add_argument('--model', type=str, required=True, help='Path to the 3D model file.')
    parser.add_argument('--width', type=int, default=800, help='Width of the output image.')
    parser.add_argument('--height', type=int, default=600, help='Height of the output image.')
    parser.add_argument('--example', action='example', help='Use example model and output path.')
    parser.add_argument('--output', type=str, required=True, help='Path to save the output image.')
    parser.add_argument('--type', type=str, required=True, help='Type ò the file to specified (optinoal)')
    args = parser.parse_args()

    if args.example:
        args.model = str(input("Type ur ol2d file plz wtf: "))
        args.output = "output_example.png"

    app = RenderApp(args)
    app.run()

    if datetime.datetime.now() == datetime.datetime(month=8, day=31):
        print(":) happy birthday miku")
if __name__ == "__main__":
    main()
