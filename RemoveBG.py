#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# RemoveBG-gimp3.py
# A GIMP 3.0 plugin to remove backgrounds from images using AI
# with an option to process all open images.
# Original author: James Huang <elastic192@gmail.com>
# Modified by: Tech Archive <medium.com/@techarchive>
# Converted to GIMP 3.0: 2024

import sys
import os
import tempfile
import subprocess
import configparser
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, GimpUi, GLib, Gtk, Gio

tupleModel = [
    "u2net",
    "u2net_human_seg",
    "u2net_cloth_seg",
    "u2netp",
    "silueta",
    "isnet-general-use",
    "isnet-anime",
    "sam"
]

def load_config():
    """Load configuration from config.ini file"""
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
    
    # Set default values
    config['Paths'] = {
        'rembg_executable': 'rembg.exe'
    }
    config['Settings'] = {
        'default_alpha_matting_value': '15',
        'default_model': '0',
        'default_as_mask': 'False',
        'default_alpha_matting': 'False',
        'default_make_square': 'False',
        'default_process_all_images': 'False'
    }
    config['Debug'] = {
        'debug_enabled': 'False'
    }
    
    # Load from file if it exists
    if os.path.exists(config_path):
        config.read(config_path)
    
    return config

class RemoveBGPlugin(Gimp.PlugIn):

    def __init__(self):
        super().__init__()
        self.config = load_config()

    def do_query_procedures(self):
        return ["python-fu-remove-bg"]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        proc = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN,
            self.run, None
        )
        proc.set_image_types("RGB*, GRAY*")
        proc.set_menu_label("AI Remove Background...")
        proc.add_menu_path("<Image>/Python-Fu/")
        proc.set_documentation(
            "AI Remove image background",
            "Remove image backgrounds using AI with an option to process all open images.",
            name
        )
        proc.set_attribution("Tech Archive", "GPLv3", "2024")
        return proc

    def remove_background_from_image(self, image, as_mask, sel_model, alpha_matting, ae_value, make_square):
        """Remove background from a single image"""
        removeTmpFile = True
        tdir = tempfile.gettempdir()
        # Use unique temporary files to avoid conflicts
        import time
        timestamp = str(int(time.time() * 1000))
        jpgFile = os.path.join(tdir, f"Temp-gimp-{timestamp}.jpg")
        pngFile = os.path.join(tdir, f"Temp-gimp-{timestamp}.png")

        try:
            layers = image.get_layers()
            if not layers:
                return False, "No layers found in image"
            
            curLayer = layers[0]  # Get the first layer
            success, x1, y1 = curLayer.get_offsets()
            if not success:
                x1, y1 = 0, 0
            if self.config.getboolean('Debug', 'debug_enabled'):
                Gimp.message(f"DEBUG: Layer offsets - x1: {x1}, y1: {y1}")

            # Export the current layer to a temporary JPEG file
            file_obj = Gio.File.new_for_path(jpgFile)
            export_result = Gimp.file_save(
                Gimp.RunMode.NONINTERACTIVE,
                image, file_obj, None
            )

            # Get rembg executable path from config
            rembgExe = self.config.get('Paths', 'rembg_executable')

            # Build the rembg command using direct executable path
            # Ensure all arguments are strings for subprocess.Popen()
            cmd = [
                str(rembgExe), 'i', '-m', str(tupleModel[sel_model])
            ]
            if alpha_matting:
                cmd.extend(['-a', '-ae', str(ae_value)])
            cmd.extend([str(jpgFile), str(pngFile)])
            
            # Print the command for debugging if enabled
            if self.config.getboolean('Debug', 'debug_enabled'):
                terminal_cmd = ' '.join(cmd)
                Gimp.message(f"DEBUG: Command: {terminal_cmd}")

            try:
                # Execute the command and capture output using subprocess.Popen
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    text=True
                )
                
                stdout, stderr = process.communicate()
                
                if process.returncode != 0:
                    return False, f"rembg error (code {process.returncode}): {stderr}"
                    
            except Exception as subprocess_error:
                if self.config.getboolean('Debug', 'debug_enabled'):
                    Gimp.message(f"DEBUG: Subprocess exception: {type(subprocess_error).__name__}: {subprocess_error}")
                return False, f"Subprocess error: {str(subprocess_error)}"

            # Load the output PNG as a new layer
            if os.path.exists(pngFile):
                # Load the new image
                file_obj = Gio.File.new_for_path(pngFile)
                loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, file_obj)
                loaded_layers = loaded_image.get_layers()
                if loaded_layers:
                    # Get the layer from the loaded image
                    source_layer = loaded_layers[0]
                    
                    # Create a new layer directly from the source drawable
                    newlayer = Gimp.Layer.new_from_drawable(source_layer, image)
                    
                    # Insert the new layer into the target image at the top
                    image.insert_layer(newlayer, None, 0)
                    
                    # Hide the original layer so the background-removed version is visible
                    curLayer.set_visible(False)
                    
                    # Set layer offsets
                    newlayer.set_offsets(x1, y1)

                    if as_mask:
                        # Create and add mask if the option is selected
                        mask = newlayer.create_mask(Gimp.AddMaskType.ALPHA)
                        newlayer.add_mask(mask)
                    else:
                        # Create a new white background layer
                        white_bg_layer = Gimp.Layer.new(
                            image, 
                            "White Background", 
                            image.get_width(), 
                            image.get_height(),
                            Gimp.ImageType.RGB_IMAGE, 
                            100.0, 
                            Gimp.LayerMode.NORMAL
                        )
                        white_bg_layer.fill(Gimp.FillType.WHITE)

                        # Ensure the white background is at the bottom, newlayer on top
                        image.insert_layer(white_bg_layer, None, -1)
                        image.reorder_item(newlayer, None, 0)

                    # Handle the "Make Square" option
                    if make_square:
                        # Get the current width and height of the image
                        img_width = image.get_width()
                        img_height = image.get_height()

                        # Determine the longer side (either width or height)
                        max_side = max(img_width, img_height)

                        # Resize the canvas to make the image square
                        image.resize(max_side, max_side, (max_side - img_width) // 2, (max_side - img_height) // 2)

                # Clean up the loaded image
                loaded_image.delete()
            else:
                return False, "Output PNG file was not created."

        except Exception as e:
            if self.config.getboolean('Debug', 'debug_enabled'):
                Gimp.message(f"DEBUG: Exception caught: {type(e).__name__}: {str(e)}")
                import traceback
                Gimp.message(f"DEBUG: Traceback: {traceback.format_exc()}")
            return False, f"Failed to execute rembg: {str(e)}"
        finally:
            # Clean up temporary files
            if removeTmpFile:
                try:
                    if os.path.exists(jpgFile):
                        os.remove(jpgFile)
                    if os.path.exists(pngFile):
                        os.remove(pngFile)
                except Exception:
                    pass

        return True, "Success"

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        GimpUi.init(procedure.get_name())

        # Default values from config
        as_mask = self.config.getboolean('Settings', 'default_as_mask')
        sel_model = self.config.getint('Settings', 'default_model')
        alpha_matting = self.config.getboolean('Settings', 'default_alpha_matting')
        ae_value = self.config.getint('Settings', 'default_alpha_matting_value')
        make_square = self.config.getboolean('Settings', 'default_make_square')
        process_all_images = self.config.getboolean('Settings', 'default_process_all_images')

        # --- Settings Dialog ---
        if run_mode == Gimp.RunMode.INTERACTIVE:
            dialog = Gtk.Dialog(
                title="AI Remove Background Settings",
                transient_for=None, flags=0
            )
            dialog.add_buttons(
                Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OK, Gtk.ResponseType.OK
            )
            box = dialog.get_content_area()
            box.set_spacing(12)
            box.set_border_width(12)

            # Use as Mask checkbox
            mask_check = Gtk.CheckButton(label="Use as Mask")
            mask_check.set_active(False)
            box.pack_start(mask_check, False, False, 0)

            # Model selection
            model_label = Gtk.Label(label="Model:")
            model_label.set_halign(Gtk.Align.START)
            box.pack_start(model_label, False, False, 0)
            
            model_combo = Gtk.ComboBoxText()
            for model in tupleModel:
                model_combo.append_text(model)
            model_combo.set_active(0)
            box.pack_start(model_combo, False, False, 0)

            # Alpha Matting checkbox
            alpha_check = Gtk.CheckButton(label="Alpha Matting")
            alpha_check.set_active(False)
            box.pack_start(alpha_check, False, False, 0)

            # Alpha Matting Erode Size
            ae_label = Gtk.Label(label="Alpha Matting Erode Size (1-100):")
            ae_label.set_halign(Gtk.Align.START)
            ae_adj = Gtk.Adjustment(15, 1, 100, 1, 10, 0)
            ae_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=ae_adj)
            ae_scale.set_digits(0)
            ae_scale.set_value_pos(Gtk.PositionType.RIGHT)
            box.pack_start(ae_label, False, False, 0)
            box.pack_start(ae_scale, True, True, 0)

            # Make Square checkbox
            square_check = Gtk.CheckButton(label="Make Square")
            square_check.set_active(False)
            box.pack_start(square_check, False, False, 0)

            # Process all images checkbox
            all_images_check = Gtk.CheckButton(label="Process all open images")
            all_images_check.set_active(False)
            box.pack_start(all_images_check, False, False, 0)

            dialog.show_all()

            resp = dialog.run()
            if resp == Gtk.ResponseType.OK:
                as_mask = mask_check.get_active()
                sel_model = model_combo.get_active()
                alpha_matting = alpha_check.get_active()
                ae_value = int(ae_scale.get_value())
                make_square = square_check.get_active()
                process_all_images = all_images_check.get_active()
            else:
                dialog.destroy()
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
            dialog.destroy()

        # Process images
        try:
            if process_all_images:
                images = Gimp.list_images()
                for img in images:
                    img.undo_group_start()
                    success, message = self.remove_background_from_image(
                        img, as_mask, sel_model, alpha_matting, ae_value, make_square
                    )
                    img.undo_group_end()
                    if not success:
                        return procedure.new_return_values(
                            Gimp.PDBStatusType.EXECUTION_ERROR,
                            GLib.Error(f"Error processing image: {message}")
                        )
            else:
                image.undo_group_start()
                success, message = self.remove_background_from_image(
                    image, as_mask, sel_model, alpha_matting, ae_value, make_square
                )
                image.undo_group_end()
                if not success:
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.EXECUTION_ERROR,
                        GLib.Error(f"Error: {message}")
                    )

        except Exception as e:
            if not process_all_images:
                image.undo_group_end()
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR,
                GLib.Error(str(e))
            )

        Gimp.displays_flush()

        if run_mode == Gimp.RunMode.INTERACTIVE:
            Gimp.message("Background removal complete!")

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

if __name__ == '__main__':
    Gimp.main(RemoveBGPlugin.__gtype__, sys.argv)