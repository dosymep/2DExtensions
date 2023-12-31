# -*- coding: utf-8 -*-

import clr

clr.AddReference('System')
clr.AddReference("System.Windows.Forms")

clr.AddReference('ClassLibrary2.dll')
clr.AddReference('MathNet.Numerics.dll')
clr.AddReference('Xceed.Wpf.Toolkit.dll')

clr.AddReference("dosymep.Revit.dll")
clr.AddReference("dosymep.Bim4Everyone.dll")

import dosymep

clr.ImportExtensions(dosymep.Revit)
clr.ImportExtensions(dosymep.Bim4Everyone)

import System
from System.Windows.Input import ICommand
from Autodesk.Revit.DB import *

import pyevent  # pylint: disable=import-error
import os.path as op
from pyrevit import forms
from pyrevit import script
from pyrevit import revit
from pyrevit import EXEC_PARAMS
from pyrevit.forms import Reactive, reactive

from dosymep_libs.bim4everyone import *

doc = __revit__.ActiveUIDocument.Document
view = doc.ActiveView


class ElementWall:
    def __init__(self, wall=None, trans=None):
        self.wall = wall
        self.trans = trans

    def __eq__(self, other):
        return (self.wall.Id == other.wall.Id
                and self.trans.Origin.IsAlmostEqualTo(other.trans.Origin))

    def __hash__(self):
        # Нужно не точное сравнение для XYZ
        return 0  # hash((self.wall.Id, self.trans.Origin))


class MainWindow(forms.WPFWindow):
    def __init__(self, ):
        self._context = None
        self.xaml_source = op.join(op.dirname(__file__), 'MainWindow.xaml')
        super(MainWindow, self).__init__(self.xaml_source)

    def button_ok_click(self, sender, e):
        self.DialogResult = True

    def button_cancel_click(self, sender, e):
        self.DialogResult = False


class MainWindowViewModel(Reactive):
    def __init__(self, legend_name, legend_scale, walls, base_legend, legend_names, *args):
        Reactive.__init__(self, *args)

        self.error_text = None
        self.__legend_name = legend_name
        self.__legend_scale = legend_scale

        self.__walls = walls
        self.__base_legend = base_legend
        self.__legend_names = legend_names
        self.__create_legend_command = CreateLegendCommand(self)

    @reactive
    def error_text(self):
        return self.__error_text

    @error_text.setter
    def error_text(self, value):
        self.__error_text = value

    @reactive
    def legend_name(self):
        return self.__legend_name

    @legend_name.setter
    def legend_name(self, value):
        self.__legend_name = value

    @reactive
    def legend_scale(self):
        return self.__legend_scale

    @legend_scale.setter
    def legend_scale(self, value):
        self.__legend_scale = value

    @reactive
    def walls(self):
        return self.__walls

    @walls.setter
    def walls(self, value):
        self.__walls = value

    @reactive
    def base_legend(self):
        return self.__base_legend

    @base_legend.setter
    def base_legend(self, value):
        self.__base_legend = value

    @reactive
    def legend_names(self):
        return self.__legend_names

    @legend_names.setter
    def legend_names(self, value):
        self.__legend_names = value

    @property
    def create_legend_command(self):
        return self.__create_legend_command


class CreateLegendCommand(ICommand):
    CanExecuteChanged, _canExecuteChanged = pyevent.make_event()

    def __init__(self, view_model, *args):
        ICommand.__init__(self, *args)
        self.__view_model = view_model
        self.__view_model.PropertyChanged += self.ViewModel_PropertyChanged

    def add_CanExecuteChanged(self, value):
        self.CanExecuteChanged += value

    def remove_CanExecuteChanged(self, value):
        self.CanExecuteChanged -= value

    def OnCanExecuteChanged(self):
        self._canExecuteChanged(self, System.EventArgs.Empty)

    def ViewModel_PropertyChanged(self, sender, e):
        self.OnCanExecuteChanged()

    def CanExecute(self, parameter):
        if not self.__view_model.legend_name:
            self.__view_model.error_text = "Заполните наименование легенды."
            return False

        if not NamingUtils.IsValidName(self.__view_model.legend_name):
            self.__view_model.error_text = "Недопустимое наименование легенды."
            return False

        if not self.__view_model.legend_scale:
            self.__view_model.error_text = "Заполните масштаб."
            return False

        if not self.__is_int(self.__view_model.legend_scale):
            self.__view_model.error_text = "Масштаб должен быть целым числом."
            return False

        if int(self.__view_model.legend_scale) <= 0:
            self.__view_model.error_text = "Масштаб должен быть неотрицательным числом."
            return False

        if not View.IsValidViewScale(int(self.__view_model.legend_scale)):
            self.__view_model.error_text = "Масштаб должен быть в диапазоне от 1 до 24000."
            return False

        self.__view_model.error_text = None
        return True

    def Execute(self, parameter):
        scale = 1
        walls = self.__view_model.walls
        legend_name = self.__view_model.legend_name
        legend_scale = self.__view_model.legend_scale
        base_legend = self.__view_model.base_legend
        legend_names = self.__view_model.legend_names

        while legend_name in legend_names:
            legend_name = legend_name + " копия"

        transform = Transform.CreateTranslation(XYZ.Zero)
        transform = transform.ScaleBasis(scale)

        legend = view
        with revit.Transaction("BIM: Создание жука по плану этажа"):
            legend_id = base_legend.Duplicate(ViewDuplicateOption.Duplicate)
            legend = doc.GetElement(legend_id)
            legend.Name = legend_name
            legend.SetParamValue(BuiltInParameter.VIEW_SCALE_PULLDOWN_METRIC, int(legend_scale))
            for wall in walls:
                if '(В)' not in wall.wall.Name:
                    curve = wall.wall.Location.Curve
                    scaled_curve = curve.CreateTransformed(transform.Multiply(wall.trans))
                    doc.Create.NewDetailCurve(legend, scaled_curve)


        UIDocument(doc).ActiveView = legend


    @staticmethod
    def __is_int(value):
        try:
            int(value)
            return True
        except:
            return False


class ExportWall2D(IExportContext2D):
    def __init__(self, document, link_instances):
        self.__document = document
        self.__walls_list = set()
        self.__link_instances = link_instances

    def OnElementBegin2D(self, node):
        element = node.Document.GetElement(node.ElementId)
        if not element.InAnyCategory(BuiltInCategory.OST_Walls):
            return RenderNodeAction.Skip

        if node.LinkInstanceId.IsNull():
            self.__walls_list.add(ElementWall(wall=element, trans=Transform.Identity))
            return RenderNodeAction.Proceed

        link_instance = next((link_instance for link_instance in self.__link_instances
                              if link_instance.Id == node.LinkInstanceId))

        transform = link_instance.GetTotalTransform() if link_instance else Transform.Identity
        self.__walls_list.add(ElementWall(wall=element, trans=transform))

        return RenderNodeAction.Proceed

    def get_element_list(self):
        return self.__walls_list


    def OnCurve(self, node):
        return RenderNodeAction.Skip


    def OnElementBegin(self, element_id):
        return RenderNodeAction.Skip


    def OnElementEnd(self, element_id):
        pass


    def OnFaceBegin(self, node):
        return RenderNodeAction.Skip


    def OnFaceEnd(self, node):
        pass


    def OnInstanceBegin(self, node):
        return RenderNodeAction.Skip


    def OnInstanceEnd(self, node):
        pass


    def OnLinkBegin(self, node):
        return RenderNodeAction.Proceed


    def OnLinkEnd(self, node):
        pass


    def OnLight(self, node):
        pass


    def OnMaterial(self, node):
        pass


    def OnPolymesh(self, node):
        pass


    def OnRPC(self, node):
        pass


    def OnElementEnd2D(self, node):
        return None


    def OnFaceEdge2D(self, node):
        return RenderNodeAction.Skip


    def OnFaceSilhouette2D(self, node):
        return RenderNodeAction.Skip


    def OnLineSegment(self, segment):
        return None


    def OnPolyline(self, node):
        return RenderNodeAction.Skip


    def OnPolylineSegments(self, segments):
        return None


    def OnText(self, node):
        return None


    def Finish(self):
        pass


    def Start(self):
        return True


    def IsCanceled(self):
        return False


    def OnViewBegin(self, node):
        return RenderNodeAction.Proceed


    def OnViewEnd(self, element_id):
        pass


@notification()
@log_plugin(EXEC_PARAMS.command_name)
def script_execute(plugin_logger):
    if view.ViewType != ViewType.FloorPlan:
        forms.alert("Активный вид должен быть планом этажа.", exitscript=True)

    link_instances = list(FilteredElementCollector(doc)
                          .OfCategory(BuiltInCategory.OST_RvtLinks)
                          .ToElements())

    export_wall = ExportWall2D(doc, link_instances)
    exporter = CustomExporter(doc, export_wall)
    exporter.Export(view)

    walls = export_wall.get_element_list()
    if not walls:
        forms.alert("На активном виде нет стен.", exitscript=True)

    legends = (x for x in FilteredElementCollector(doc).OfClass(View) if x.ViewType == ViewType.Legend)
    legends_names = (x.Name for x in legends)
    legends = (x for x in legends if x.CanViewBeDuplicated(ViewDuplicateOption.Duplicate))
    base_legend = next(legends, None)
    if not base_legend:
        forms.alert("В модели нет легенды для копирования.", exitscript=True)

    main_window = MainWindow()
    main_window.DataContext = (
        MainWindowViewModel(
            "Легенда для вида " + view.Name, "50",
            walls, base_legend, legends_names))

    if not main_window.show_dialog():
        script.exit()


script_execute()
