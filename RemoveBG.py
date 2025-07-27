#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Modified GIMP plugin to remove backgrounds from images
# with an option to process all open images.
# Original author: James Huang <elastic192@gmail.com>
# Modified by: Tech Archive <medium.com/@techarchive>
# Modified by: Guy Vardi 
# Date: 27/7/25 

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
        'python_executable': 'python'
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

    def _create_temp_files(self):
        """Create temporary file paths for processing"""
        tdir = tempfile.gettempdir()
        import time
        timestamp = str(int(time.time() * 1000))
        jpg_file = os.path.join(tdir, f"Temp-gimp-{timestamp}.jpg")
        png_file = os.path.join(tdir, f"Temp-gimp-{timestamp}.png")
        return jpg_file, png_file

    def _get_layer_info(self, image):
        """Get layer information and validate image"""
        layers = image.get_layers()
        if not layers:
            return None, None, "No layers found in image"
        
        cur_layer = layers[0]
        success, x1, y1 = cur_layer.get_offsets()
        if not success:
            x1, y1 = 0, 0
            
        if self.config.getboolean('Debug', 'debug_enabled'):
            Gimp.message(f"DEBUG: Layer offsets - x1: {x1}, y1: {y1}")
            
        return cur_layer, (x1, y1), None

    def _export_layer_to_jpeg(self, image, jpg_file):
        """Export the current layer to a temporary JPEG file"""
        file_obj = Gio.File.new_for_path(jpg_file)
        export_result = Gimp.file_save(
            Gimp.RunMode.NONINTERACTIVE,
            image, file_obj, None
        )
        return export_result

    def _build_rembg_command(self, sel_model, alpha_matting, ae_value, jpg_file, png_file):
        """Build the rembg command with all parameters"""
        python_exe = self.config.get('Paths', 'python_executable', fallback='python')
        
        cmd = [
            str(python_exe), '-m', 'rembg.cli', 'i', '-m', str(tupleModel[sel_model])
        ]
        if alpha_matting:
            cmd.extend(['-a', '-ae', str(ae_value)])
        cmd.extend([str(jpg_file), str(png_file)])
        
        if self.config.getboolean('Debug', 'debug_enabled'):
            terminal_cmd = ' '.join(cmd)
            Gimp.message(f"DEBUG: Command: {terminal_cmd}")
            
        return cmd

    def _execute_rembg(self, cmd):
        """Execute the rembg command and handle errors"""
        try:
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
            
        return True, None

    def _load_processed_image(self, png_file):
        """Load the processed PNG image and extract the layer"""
        if not os.path.exists(png_file):
            return None, "Output PNG file was not created."
            
        file_obj = Gio.File.new_for_path(png_file)
        loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, file_obj)
        loaded_layers = loaded_image.get_layers()
        
        if not loaded_layers:
            loaded_image.delete()
            return None, "No layers found in processed image."
            
        source_layer = loaded_layers[0]
        return source_layer, loaded_image, None

    def _create_new_layer(self, source_layer, image, offsets):
        """Create a new layer from the processed image"""
        x1, y1 = offsets
        
        # Create a new layer directly from the source drawable
        new_layer = Gimp.Layer.new_from_drawable(source_layer, image)
        
        # Insert the new layer into the target image at the top
        image.insert_layer(new_layer, None, 0)
        
        # Set layer offsets
        new_layer.set_offsets(x1, y1)
        
        return new_layer

    def _handle_mask_mode(self, new_layer):
        """Handle mask creation if as_mask is True"""
        mask = new_layer.create_mask(Gimp.AddMaskType.ALPHA)
        new_layer.add_mask(mask)

    def _handle_background_replacement(self, image, new_layer):
        """Handle background replacement with white background"""
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
        image.reorder_item(new_layer, None, 0)

    def _make_image_square(self, image):
        """Resize the image to make it square if requested"""
        img_width = image.get_width()
        img_height = image.get_height()

        # Determine the longer side (either width or height)
        max_side = max(img_width, img_height)

        # Resize the canvas to make the image square
        image.resize(max_side, max_side, (max_side - img_width) // 2, (max_side - img_height) // 2)

    def _cleanup_temp_files(self, jpg_file, png_file):
        """Clean up temporary files"""
        try:
            if os.path.exists(jpg_file):
                os.remove(jpg_file)
            if os.path.exists(png_file):
                os.remove(png_file)
        except Exception:
            pass

    def remove_background_from_image(self, image, as_mask, sel_model, alpha_matting, ae_value, make_square):
        """Remove background from a single image - main orchestrator method"""
        jpg_file, png_file = self._create_temp_files()
        loaded_image = None

        try:
            # Get layer information
            cur_layer, offsets, error = self._get_layer_info(image)
            if error:
                return False, error

            # Export layer to JPEG
            self._export_layer_to_jpeg(image, jpg_file)

            # Build and execute rembg command
            cmd = self._build_rembg_command(sel_model, alpha_matting, ae_value, jpg_file, png_file)
            success, error = self._execute_rembg(cmd)
            if not success:
                return False, error

            # Load processed image
            source_layer, loaded_image, error = self._load_processed_image(png_file)
            if error:
                return False, error

            # Create new layer
            new_layer = self._create_new_layer(source_layer, image, offsets)
            
            # Hide the original layer
            cur_layer.set_visible(False)

            # Handle mask or background replacement
            if as_mask:
                self._handle_mask_mode(new_layer)
            else:
                self._handle_background_replacement(image, new_layer)

            # Handle square option
            if make_square:
                self._make_image_square(image)

        except Exception as e:
            if self.config.getboolean('Debug', 'debug_enabled'):
                Gimp.message(f"DEBUG: Exception caught: {type(e).__name__}: {str(e)}")
                import traceback
                Gimp.message(f"DEBUG: Traceback: {traceback.format_exc()}")
            return False, f"Failed to execute rembg: {str(e)}"
        finally:
            # Clean up resources
            if loaded_image:
                loaded_image.delete()
            self._cleanup_temp_files(jpg_file, png_file)

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
                # Get all open images using GIMP 3.0 API
                images_array = Gimp.get_images()
                if not images_array:
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.EXECUTION_ERROR,
                        GLib.Error("No open images found")
                    )
                
                # Gimp.get_images() returns a Python list, not a NULL-terminated array
                images = list(images_array)  # Convert to list if needed
                Gimp.message(f"DEBUG: Total images in list: {len(images)}")
                
                # Filter for valid images (those that have layers)
                valid_images = []
                for img in images:
                    try:
                        layers = img.get_layers()
                        if layers and len(layers) > 0:
                            valid_images.append(img)
                            Gimp.message(f"DEBUG: Valid image found: {img}")
                    except Exception as e:
                        Gimp.message(f"DEBUG: Skipping invalid image: {e}")
                
                Gimp.message(f"DEBUG: Valid images found: {len(valid_images)}")
                images = valid_images
                
                # Process each image
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