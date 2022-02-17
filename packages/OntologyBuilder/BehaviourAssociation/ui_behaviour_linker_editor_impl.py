import os.path
import sys
from copy import deepcopy
from os.path import join

from PyQt5 import QtCore
from PyQt5 import QtWidgets

from Common.common_resources import Redirect
from Common.common_resources import Stream
from Common.common_resources import TEMPLATE_ENTITY_OBJECT
from Common.common_resources import getData
from Common.common_resources import getOntologyName
from Common.common_resources import indexList
from Common.common_resources import putData
from Common.common_resources import walkDepthFirstFnc
from Common.ontology_container import OntologyContainer
from Common.pop_up_message_box import makeMessageBox
from Common.record_definitions_equation_linking import EntityBehaviour
# from Common.record_definitions_equation_linking import NodeArcAssociations
from Common.record_definitions_equation_linking import VariantRecord
from Common.record_definitions_equation_linking import functionGetObjectsFromObjectStringID
from Common.record_definitions_equation_linking import functionMakeObjectStringID
from Common.resource_initialisation import DIRECTORIES
from Common.resource_initialisation import FILES
from Common.resource_initialisation import checkAndFixResources
from Common.resources_icons import roundButton
from Common.ui_string_dialog_impl import UI_String
from Common.ui_two_list_selector_dialog_impl import UI_TwoListSelector
from OntologyBuilder.BehaviourAssociation.ui_behaviour_linker_editor import Ui_MainWindow
from OntologyBuilder.OntologyEquationEditor.resources import AnalyseBiPartiteGraph
from OntologyBuilder.OntologyEquationEditor.resources import isVariableInExpression
from OntologyBuilder.OntologyEquationEditor.resources import makeLatexDoc
from OntologyBuilder.OntologyEquationEditor.resources import renderExpressionFromGlobalIDToInternal
from OntologyBuilder.OntologyEquationEditor.resources import showPDF
from OntologyBuilder.OntologyEquationEditor.variable_framework import findDependentVariables
from OntologyBuilder.OntologyEquationEditor.variable_framework import makeIncidenceDictionaries

base_variant = "base"  # RULE: nomenclature for base case

pixel_or_text = "text"  # NOTE: variable to set the mode


class Selector(QtCore.QObject):
  """
  Generates a selector for a set of radio buttons.
  The radio buttons are added to a given layout.
  Layouts are handling the buttons in autoexclusive mode.
  The current version is exclusively operating in autoexclusive mode even though there is a variable
    indicating to opposite. It does not work if not every button is set to autoexclusive explicitly. In that case
    the exclusive mode must be handled manually.
    TODO: implement manual handling -- tip: define new button adding group-internal communication
  """
  radio_signal = QtCore.pyqtSignal(str, int)

  def __init__(self, radio_class, receiver, label_list, layout, mode="text", autoexclusive=True):
    super().__init__()
    self.radio_class = radio_class
    self.labels = label_list
    self.layout = layout
    self.mode = mode
    self.autoexclusive = autoexclusive
    self.selected_ID = None
    self.show_list = []

    self.radios = {}
    self.label_indices, \
    self.label_indices_inverse = indexList(self.labels)

    self.makeSelector()
    self.radio_signal.connect(receiver)

  def __radioAutoExclusive(self):
    for ID in self.radios:
      self.radios[ID].setAutoExclusive(self.autoexclusive)

  def getStrID(self):
    ID = self.selected_ID
    if ID == None:
      return None
    return self.label_indices[ID]

  def getID(self, str_ID):
    return self.label_indices_inverse[str_ID]

  def makeSelector(self):
    if self.mode == "text":
      self.makeTextSelector()
    elif self.mode == "pixelled":
      self.makePixelSelector()
    else:
      raise

  def makeTextSelector(self):
    for ID in self.label_indices:
      label = self.labels[ID]
      # self.radios[ID] = QtWidgets.QRadioButton(label)
      self.radios[ID] = QtWidgets.QCheckBox(label)
      # if self.autoexclusive:
      #   self.radios[ID].setAutoExclusive(True)
      # self.radios[ID].setAutoExclusive(self.autoexclusive)
      self.layout.addWidget(self.radios[ID])
      self.__radioAutoExclusive()
      self.radios[ID].toggled.connect(self.selector_toggled)

  def makePixelSelector(self):

    for ID in self.label_indices:
      icon, label, size = self.labels[ID]
      label = QtWidgets.QLabel()
      self.radios[ID] = QtWidgets.QRadioButton(label)
      self.radios[ID].setIcon(icon)
      self.radios[ID].setIconSize(size)
      self.radios[ID].resize(0, 0)  # Note: not sure what I am doing here -- reduces gaps between

      # if self.autoexclusive:
      #   self.radios[ID].setAutoExclusive(False)
      self.__radioAutoExclusive()
      self.layout.addWidget(self.radios[ID])

      self.radios[ID].toggled.connect(self.selector_toggled)

  def showList(self, show):
    self.show_list = show
    self.showIt()
    # self.resetChecked()

  def showIt(self):
    for ID in self.radios:
      self.radios[ID].setAutoExclusive(False)
      self.radios[ID].setChecked(False)
      if ID not in self.show_list:
        self.radios[ID].hide()
      else:
        self.radios[ID].show()
    self.__radioAutoExclusive()

  def reset(self):
    self.showList([])

  # def selector_pressed(self):
  #   print("debugging -- pressed")

  def selector_toggled(self, toggled):
    # print("debugging -- toggled", toggled)

    if toggled:
      ID = self.getToggled()

      if ID >= 0:
        self.radio_signal.emit(self.radio_class, ID)

  def getToggled(self):

    count = -1
    ID = -1
    for ID_ in self.radios:
      count += 1
      if self.radios[ID_].isChecked():
        # print("goit it :", label)
        ID = count
        self.radios[ID].setCheckState(False)

    self.selected_ID = ID

    return ID

  def resetChecked(self):
    for ID in self.radios:
      self.radios[ID].setDown(False)


class MainWindowImpl(QtWidgets.QMainWindow):
  def __init__(self, icon_f):

    super().__init__()
    self.ui = Ui_MainWindow()
    self.ui.setupUi(self)

    roundButton(self.ui.pushButtonInformation, "info", tooltip="information")
    roundButton(self.ui.pushButtonSave, "save", tooltip="save entity behaviour")
    roundButton(self.ui.pushButtonCancel, "exit", tooltip="cancel and exit")
    roundButton(self.ui.pushButtonDelete, "delete", tooltip="delete current var/eq tree")
    roundButton(self.ui.pushButtonMakeLatex, "LaTex", tooltip="make latex files for all objects")
    roundButton(self.ui.pushButtonViewLatex, "variable_show", tooltip="show latex")
    roundButton(self.ui.pushButtonUpdate, "update", tooltip="update tree")

    self.ui.groupBoxControls.hide()
    self.ui.pushButtonLeft.hide()
    self.ui.pushButtonRight.hide()
    self.ui.pushButtonMakeLatex.hide()
    self.ui.pushButtonViewLatex.hide()

    # output streaming
    REDIRECT_STDOUT = False  # TODO: does not work if there are problems in graph generation (missing file)
    REDIRECT_ERROR = False

    stdOut = Redirect(self.ui.msgTextBoxStandardOut)
    stdOut.home()
    stdError = Redirect(self.ui.msgTextBoxErrorOut)
    stdError.home()
    if REDIRECT_STDOUT:
      sys.stdout = Stream(newText=stdOut.update)
    if REDIRECT_ERROR:
      sys.stderr = Stream(newText=stdError.update)

    # first get ontology
    self.ontology_name = getOntologyName(task=icon_f)

    # check for infrastructure
    checkAndFixResources(self.ontology_name, stage="ontology_stage_2")

    # attach ontology
    self.ontology_container = OntologyContainer(self.ontology_name)
    self.location = DIRECTORIES["latex_doc_location"] % self.ontology_name

    self.ontology_location = DIRECTORIES["ontology_location"] % str(self.ontology_name)

    self.reduced_network_node_list = self.ontology_container.list_reduced_network_node_objects
    self.reduced_arc_list = self.ontology_container.list_reduced_network_arc_objects

    # instantiate entity behaviours
    networks = self.ontology_container.list_inter_branches
    # entities_list = self.reduced_network_node_list

    self.arc_objects = self.ontology_container.list_arc_objects_on_networks
    self.node_objects = self.ontology_container.list_inter_node_objects_tokens  # list_node_objects_on_networks_with_tokens
    entities_list = []
    for nw in self.node_objects:
      for o in self.node_objects[nw]:
        obj = TEMPLATE_ENTITY_OBJECT % (nw, "node", o, "base")
        entities_list.append(obj)
    for nw in self.arc_objects:
      for o in self.arc_objects[nw]:
        obj = TEMPLATE_ENTITY_OBJECT % (nw, "arc", o, "base")  # RULE: "base" is used for the base bipartite graph
        entities_list.append(obj)

    self.entity_behaviours = EntityBehaviour(entities_list)

    self.list_linked_equations = self.__getFilteredEquationList("interface_link_equation")
    # print("debugging")

    equations_label_list, \
    self.equation_information, \
    self.equation_inverse_index = self.__makeEquationAndIndexLists()
    self.rules = {}

    # get existing data
    self.__readVariableAssignmentToEntity()

    # interface components
    self.layout_InterNetworks = QtWidgets.QVBoxLayout()  # Vertical Box with horizontal boxes of radio buttons & labels
    self.ui.scrollAreaWidgetContentsInterNetworks.setLayout(self.layout_InterNetworks)

    # initialisations
    # network selector
    self.radio_InterNetworks = Selector("InterNetworks",
                                        self.radioReceiverState,
                                        networks,
                                        self.layout_InterNetworks)

    self.selected_InterNetwork_ID = None
    self.selected_Entity_ID = None
    self.selected_variant_ID = None
    self.selected_variant_str_ID = "base"
    self.radio_index = None
    self.selected_base_variable = None
    self.rightListEquationIDs = []
    self.rightListEquationIDs_radio_ID = []

    self.match_equations_label_list = []
    self.match_equation_ID = {}
    # self.node_arc = "nodes"
    self.node_arc = self.ui.tabWidgetNodesArcs.tabText(self.ui.tabWidgetNodesArcs.currentIndex())

    # controls
    self.actions = ["show", "duplicates", "new_variant", "edit_variant", "instantiate_variant"]

    # prepare lists
    self.current_base_var_ID = None

    # start process

    self.status_report = self.statusBar().showMessage
    self.status_report("getting started")
    self.entity_layout_clean = True
    self.variant_layout_clean = True
    self.equation_left_clean = True
    self.equation_right_clean = True
    self.selected_variant = None
    self.state = "start"

  def __readVariableAssignmentToEntity(self):
    f = FILES["variable_assignment_to_entity_object"] % self.ontology_name
    # loaded_entity_behaviours = getData(f)
    data = getData(f)
    if data:
      loaded_entity_behaviours = data["behaviours"]
      # self.node_arc_associations = data["associations"]

      if loaded_entity_behaviours:
        for entity_str_ID in loaded_entity_behaviours:  # careful there may not be all entities at least during
          # developments
          if loaded_entity_behaviours[entity_str_ID]:
            dummy = VariantRecord()
            data = loaded_entity_behaviours[entity_str_ID]
            for atr in dummy:
              if atr not in data:
                data[atr] = None
            tree = {}
            for treeStrID in data["tree"]:
              tree[int(treeStrID)] = data["tree"][treeStrID]
            data["tree"] = tree

            nodes = {}
            for nodeStrID in data["nodes"]:
              nodes[int(nodeStrID)] = data["nodes"][nodeStrID]
            data["nodes"] = nodes

            self.entity_behaviours[entity_str_ID] = VariantRecord(tree=data["tree"],
                                                                  nodes=data["nodes"],
                                                                  IDs=data["IDs"],
                                                                  root_variable=data["root_variable"],
                                                                  blocked_list=data["blocked"],
                                                                  buddies_list=data["buddies"],
                                                                  to_be_inisialised=data["to_be_initialised"])

  def getObjectSpecificationState(self):
    state = -1
    if self.radio_InterNetworks.selected_ID != None:
      state += 1
      if self.radio_Entities.selected_ID != None:
        state += 1
        if self.radio_Variants.selected_ID != None:
          state += 1
    return state

  def isCompleteSpecificationState(self):
    return self.getObjectSpecificationState() == 2

  def superviseControls(self):
    if self.isCompleteSpecificationState():
      self.ui.groupBoxControls.show()

  def __makeObjectList(self):

    self.node_arc = self.ui.tabWidgetNodesArcs.tabText(self.ui.tabWidgetNodesArcs.currentIndex())
    if self.node_arc == "nodes":
      ui = self.ui.listNodeObjects
      n = sorted(self.node_objects[self.selected_InterNetwork_strID])
    else:
      ui = self.ui.listArcObjects
      n = sorted(self.arc_objects[self.selected_InterNetwork_strID])
    ui.clear()
    ui.addItems(n)

  def on_tabWidgetNodesArcs_currentChanged(self, index):
    self.node_arc = self.ui.tabWidgetNodesArcs.tabText(self.ui.tabWidgetNodesArcs.currentIndex())
    self.__makeObjectList()

  def on_listNodeObjects_itemClicked(self, v):
    # print('debugging -- item clicked', v.text())
    # selected_InterNetwork_strID self.node_arc v.text()
    # entity_behaviours
    self.selected_object = v.text()
    self.ui.pushButtonLeft.setText('')
    self.ui.pushButtonLeft.hide()
    self.ui.groupBoxControls.hide()
    self.ui.listLeft.clear()
    self.ui.listRight.clear()
    self.ui.listVariants.clear()
    self.selected_variant_str_ID = "base"
    self.__makeVariantList(True)
    obj_str = self.__makeCurrentObjectString()
    if not self.entity_behaviours[
      obj_str]:  # self.node_arc_associations[self.selected_InterNetwork_strID]["nodes"][v.text()]:
      # self.selected_object = v.text()
      self.__makeBase()
    else:
      # print("debugging -- load")
      self.__makeVariantList(True)
      self.ui.pushButtonMakeLatex.show()
      self.ui.pushButtonViewLatex.show()

  def on_listArcObjects_itemClicked(self, v):
    # print('debugging -- item clicked', v.text())
    self.selected_object = v.text()
    self.ui.pushButtonLeft.setText('')
    self.ui.pushButtonLeft.hide()
    self.ui.groupBoxControls.hide()
    self.ui.listLeft.clear()
    self.ui.listRight.clear()
    self.ui.listVariants.clear()
    self.selected_variant_str_ID = "base"
    self.__makeVariantList(True)
    obj_str = self.__makeCurrentObjectString()
    if not self.entity_behaviours[obj_str]:
      # if self.node_arc_associations[self.selected_InterNetwork_strID]["arcs"]:
      self.selected_object = v.text()
      self.__makeBase()
    else:
      # print("debugging -- load")
      self.ui.pushButtonMakeLatex.show()
      self.ui.pushButtonViewLatex.show()

  def on_listLeft_itemClicked(self, v):
    row = self.ui.listLeft.row(v)
    # print('debugging -- item clicked', v.text(), row)
    # print("debugging -- state: ", self.state)
    var_strID, equ_strID = self.leftIndex[row]
    equation_label = v.text()
    self.getState()
    if self.state == "show":
      return

    elif self.state == "make_base":
      self.current_base_var_ID = int(var_strID)
      self.current_base_equ_ID = int(equ_strID)
      self.__makeEquationTextButton(equation_label, self.ui.pushButtonLeft, "click to accept")
    else:  # self.state == "duplicates":
      var_ID, eq_ID = self.leftIndex[row]
      self.leftListEquationIDs.remove(eq_ID)
      self.rightListEquationIDs.append(eq_ID)
      # print("debugging -- duplicates", self.leftListEquationIDs)
      # print("debugging -- blocked", self.rightListEquationIDs)
      self.leftIndex = self.__makeLeftRightList(self.leftListEquationIDs, self.ui.listLeft)
      self.rightIndex = self.__makeLeftRightList(self.rightListEquationIDs, self.ui.listRight)
      self.__makeEquationTextButton("accept", self.ui.pushButtonLeft, "click to accept")
      # print("debugging")

  def on_listRight_itemClicked(self, v):
    if self.state == "show":
      return
    row = self.ui.listRight.row(v)
    # print("debugging -- right item clicked", v.text(), row)
    # if self.state == "duplicates":
    var_ID, eq_ID = self.rightIndex[row]
    self.leftListEquationIDs.append(eq_ID)
    self.rightListEquationIDs.remove(eq_ID)
    # print("debugging -- duplicates", self.leftListEquationIDs)
    # print("debugging -- blocked", self.rightListEquationIDs)
    self.leftIndex = self.__makeLeftRightList(self.leftListEquationIDs, self.ui.listLeft)
    self.rightIndex = self.__makeLeftRightList(self.rightListEquationIDs, self.ui.listRight)

  def showVariant(self):
    self.state = "show"

  def radioReceiverState(self, radio_class, ID):
    # print("debugging -- receiver state %s" % radio_class, ID)
    # self.superviseControls()

    if radio_class == "InterNetworks":
      self.selected_InterNetwork_ID = ID
      self.selected_InterNetwork_strID = self.radio_InterNetworks.getStrID()
      self.__makeObjectList()
      self.ui.pushButtonLeft.hide()
      self.ui.pushButtonRight.hide()
      self.ui.listLeft.clear()
      self.ui.listRight.clear()

  def on_pushButtonLeft_pressed(self):
    self.getState()
    # print("debugging -- push left button state:", self.state)
    if self.state == "make_base":
      # variant = "base"
      var_ID = self.current_base_var_ID
      equ_ID = self.current_base_equ_ID
      obj_str = self.__makeCurrentObjectString()
      blocked = self.list_linked_equations
      var_equ_tree_graph, entity_assignments = self.analyseBiPartiteGraph(obj_str, var_ID, blocked)
      self.status_report("generated graph for %s" % (obj_str))
      # component = self.node_arc.strip("s")
      self.selected_variant_str_ID = "base"
      obj = self.__makeCurrentObjectString()
      self.entity_behaviours.addVariant(obj, entity_assignments)
      self.__makeVariantList(True)

      graph_file = var_equ_tree_graph.render()
      self.ui.pushButtonLeft.hide()
      self.ui.groupBoxControls.show()
      self.ui.pushButtonMakeLatex.show()
      self.ui.pushButtonViewLatex.show()

      self.ui.listLeft.clear()
      self.__makeAndDisplayEquationListLeftAndRight()
      self.ui.groupBoxControls.show()

    elif self.state in ["duplicates", "new_variant", "edit_variant"]:  # accepting
      print("debugging -- accepting >>> %s <<< reduced entity object" % self.state)

      var_ID = self.selected_base_variable
      obj_str = self.__makeCurrentObjectString()

      self.variant_list = self.__makeVariantStringList()
      if self.state in ["duplicates", "new_variant"]:
        self.selected_variant_str_ID = self.__askForNewVariantName(self.variant_list)
        self.ui.listLeft.clear()
        self.ui.listRight.clear()
        if self.state == "duplicates":
          selectedListEquationIDs = self.entity_behaviours.getEquationIDList(obj_str)
          # this is tricky: the right list may include already blocked ones.
          for e in self.rightListEquationIDs:
            if e in selectedListEquationIDs:
              selectedListEquationIDs.remove(e)
          self.leftListEquationIDs = selectedListEquationIDs

      blocked = list(set(self.list_linked_equations) | set(self.rightListEquationIDs))
      var_equ_tree_graph, entity_assignments = self.analyseBiPartiteGraph(obj_str, var_ID,
                                                                          blocked)  # self.rightListEquationIDs)
      graph_file = var_equ_tree_graph.render()
      self.status_report("generated graph for %s " % (obj_str))

      obj = self.__makeCurrentObjectString()
      self.entity_behaviours.addVariant(obj, entity_assignments)
      self.__makeVariantList(True)

      incidence_dictionary, inv_incidence_dictionary = makeIncidenceDictionaries(self.ontology_container.variables)
      d_vars, d_equs, d_vars_text, d_equs_text = findDependentVariables(self.ontology_container.variables, 95,
                                                                        self.ontology_container.indices)

      print("debugging -- collect equations for the root expression:",d_vars, d_equs, d_vars_text, d_equs_text )
      #
      # file_name = obj.replace("|", "__").replace(".","_")
      # makeLatexDoc(file_name, entity_assignments, self.ontology_container)

      # self.ui.radioButtonShowVariant.setChecked(True)

    elif self.state == "show":
      pass
      # print("debugging -- show don't do anything")

  def on_pushButtonUpdate_pressed(self):
    obj_str = self.__makeCurrentObjectString()
    # print("debugging -- update pressed %s" % self.state)
    var_ID = self.selected_base_variable
    blocked = list(set(self.list_linked_equations) or set(self.rightListEquationIDs))
    var_equ_tree_graph, entity_assignments = self.analyseBiPartiteGraph(obj_str, var_ID,
                                                                        blocked)  # self.rightListEquationIDs)
    graph_file = var_equ_tree_graph.render()
    self.status_report("generated graph for %s " % (obj_str))

    self.entity_behaviours.addVariant(obj_str, entity_assignments)
    self.__makeAndDisplayEquationListLeftAndRight()
    self.variant_list = self.__makeVariantStringList()

  def __getFilteredEquationList(self, equation_type):
    equations = []
    for e in self.ontology_container.equation_dictionary:
      entry = self.ontology_container.equation_dictionary[e]
      if entry["type"] == equation_type:
        equations.append(e)

    print("debugging -- ", equations)
    return equations

  def __makeVariantList(self, set):
    """
    gets the current variant list and builds the gui list
    """
    self.variant_list = self.__makeVariantStringList()
    if not self.variant_list:
      set = False
    self.ui.listVariants.clear()
    self.ui.listVariants.addItems(self.variant_list)
    if set:
      row = self.variant_list.index(self.selected_variant_str_ID)
      self.ui.listVariants.setCurrentRow(row)
      return True
    else:
      self.selected_variant_str_ID = "base"
      self.setState("make_base")
      return False

  def setState(self, state):
    self.state = state
    self.ui.groupBoxApplication.show()
    if state == "show":
      self.ui.radioButtonShowVariant.setChecked(True)
    elif state == "make_base":
      self.ui.radioButtonMakBase.setChecked(True)
    elif state == "duplicates":
      self.ui.radioButtonDuplicates.setChecked(True)
    elif state == "new_variant":
      self.ui.radioButtonNewVariant.setChecked(True)
    elif state == "edit_variant":
      self.ui.radioButtonEditVariant.setChecked(True)
    elif state == "instantiate_variant":
      self.ui.radioButtonInstantiateVariant.setChecked(True)

  def getState(self):
    if self.ui.radioButtonShowVariant.isChecked():
      self.state = "show"
    elif self.ui.radioButtonMakBase.isChecked():
      self.state = "make_base"
    elif self.ui.radioButtonDuplicates.isChecked():
      self.state = "duplicates"
    elif self.ui.radioButtonNewVariant.isChecked():
      self.state = "new_variant"
    elif self.ui.radioButtonEditVariant.isChecked():
      self.state = "edit_variant"
    elif self.ui.radioButtonInstantiateVariant.isChecked():
      self.state = "instantiate_variant"

  # push buttons
  def on_pushButtonRight_pressed(self):
    # print("debugging -- push right button")
    pass

  def on_listVariants_currentRowChanged(self, row):
    if self.variant_list:
      self.selected_variant_str_ID = self.variant_list[row]
      self.__makeAndDisplayEquationListLeftAndRight()
      self.ui.groupBoxControls.show()
      self.setState("show")
    else:
      self.ui.listLeft.clear()
      self.ui.listRight.clear()
      self.ui.radioButtonShowVariant.setChecked(False)
    # print("debugging -- current variant", self.selected_variant_str_ID)

  def on_pushButtonDelete_pressed(self):
    obj = self.__makeCurrentObjectString()
    self.entity_behaviours.removeVariant(obj)  # nw_str_ID, entity_label_ID, variant)
    deleted_base = self.__makeVariantList(False)
    self.ui.listLeft.clear()
    self.ui.listRight.clear()
    # self.ui.radioButtonShowVariant.setChecked(True)
    if deleted_base:
      self.current_base_var_ID = "base"
      # self.on_radioButtonShowVariant_pressed()
    self.ui.pushButtonLeft.hide()

  def on_pushButtonSave_pressed(self):
    # print("debugging -- save file")
    # self.ontology_container.writeVariables()

    f = FILES["variable_assignment_to_entity_object"] % self.ontology_name
    for obj in self.entity_behaviours:
      if self.entity_behaviours[obj]:
        try:
          self.__makeVariablesToBeValueInitialised(obj)
        except:
          print("Error -- something went wrong object: %s" % obj)
    data = {"behaviours": self.entity_behaviours}  # ,
    # "associations": self.node_arc_associations}

    # putData(self.entity_behaviours, f)
    putData(data, f)

  def on_pushButtonInformation_pressed(self):
    print("todo: not yet implemented")

  def on_radioButtonShowVariant_pressed(self):
    print("debugging -- show variant")
    if not self.variant_list:
      return

    position = self.ui.radioButtonShowVariant.isChecked()
    # print("debugging -- show variant -- toggle state:", position)

    if position:
      self.setState("show")
      self.__makeAndDisplayEquationListLeftAndRight()
    else:
      self.ui.listLeft.clear()

  def on_pushButtonMakeLatex_pressed(self):
    non_existing = []
    for obj in self.entity_behaviours:
      assignment = self.entity_behaviours[obj]
      if assignment != None:
        self.__makeLatexDocument(obj, assignment)
      else:
        non_existing.append(obj)
    if non_existing != []:
      for obj in non_existing:
        print("error -- this object does not seem to have an assignment: %s" % obj)

  def on_pushButtonViewLatex_pressed(self):
    obj = self.__makeCurrentObjectString()
    file_name = obj.replace("|", "__").replace(".", "_").replace(" ", "_")
    file = join(DIRECTORIES["latex_location"] % self.ontology_name, file_name) + ".pdf"
    if os.path.exists(file):
      showPDF(file)
    else:
      self.on_pushButtonMakeLatex_pressed()

  def on_pushButtonCancel_pressed(self):
    ans = makeMessageBox("want to exit?")
    if ans != "OK":
      return
    else:
      self.close()

  def on_radioButtonDuplicates_pressed(self):
    # print("debugging -- duplicates")
    self.setState("duplicates")

    if not self.variant_list:
      return

    entity_object_str = self.__makeCurrentObjectString()
    self.selected_base_variable = self.entity_behaviours[entity_object_str]["root_variable"]
    self.leftListEquationIDs = self.__makeDuplicateShows()
    self.leftIndex = self.__makeLeftRightList(self.leftListEquationIDs, self.ui.listLeft)
    self.ui.pushButtonLeft.hide()

  def on_radioButtonNewVariant_pressed(self):
    if not self.variant_list:
      return

    self.state = "new_variant"
    self.__makeAndDisplayEquationListLeftAndRight()  # self.selected_variant_str_ID)

  def on_radioButtonEditVariant_pressed(self):

    if not self.variant_list:
      return

    # print("debugging -- edit variant")
    self.state = "edit_variant"
    self.__makeAndDisplayEquationListLeftAndRight()

  def on_radioButtonInstantiateVariant_pressed(self):

    if not self.variant_list:
      return

    # print("debugging -- instantiate variant")

    entity_object_str = self.__makeEntityObjectStrID()
    self.__makeVariablesToBeValueInitialised(entity_object_str)

  # def on_pushButtonNodeAssociations_pressed(self):
  #   print("debugging -- token topologies network %s" % self.selected_InterNetwork_ID)
  #   if not self.selected_InterNetwork_ID:
  #     self.status_report("define network first")
  #     return
  #
  #   self.state = "token_topologies"
  #   nw = self.radio_InterNetworks.getStrID()
  #   # node_objects = self.ontology_container.list_node_objects_on_networks_with_tokens[nw]
  #   node_objects = sorted(self.node_arc_associations[nw]["nodes"].keys())
  #
  #   self.match_equations_label_list = []
  #   self.match_node_equation_inverse = {}
  #   for ID in range(0, len(self.equation_inverse_index)):
  #     eq_ID, var_ID, var_type, nw_eq, equation_label = self.equation_information[ID]
  #     if var_type == "state":
  #       self.match_equations_label_list.append(equation_label)
  #       self.match_node_equation_inverse[equation_label] = eq_ID, var_ID
  #
  #   selector = UI_MatchPairs(node_objects, self.match_equations_label_list, self.matchNodeReceiver, take_right=False)
  #   self.update()
  #   gugus = selector.exec_()

  # def on_pushButtonArcAssociations_pressed(self):
  #   print("debugging -- token topologies network %s" % self.selected_InterNetwork_ID)
  #   if not self.selected_InterNetwork_ID:
  #     self.status_report("define network first")
  #     return
  #
  #   self.state = "token_topologies"
  #   nw = self.radio_InterNetworks.getStrID()
  #   # arc_objects = self.ontology_container.list_arc_objects_on_networks[nw]
  #   arc_objects = sorted(self.node_arc_associations[nw]["arcs"].keys())
  #   self.match_equations_label_list = []
  #   self.match_arc_equation_inverse = {}
  #   for ID in range(0, len(self.equation_inverse_index)):
  #     eq_ID, var_ID, var_type, nw_eq, equation_label = self.equation_information[ID]
  #     if var_type == "transport":
  #       self.match_equations_label_list.append(equation_label)
  #       self.match_arc_equation_inverse[equation_label] = eq_ID, var_ID
  #
  #   selector = UI_MatchPairs(arc_objects, self.match_equations_label_list, self.matchArcReceiver, take_right=False)
  #   self.update()
  #   gugus = selector.exec_()

  # def matchNodeReceiver(self, selection):
  #   print("match receiver -- selection", selection)
  #   nw_str_ID = self.radio_InterNetworks.getStrID()
  #   for node_object, equation in selection:
  #     print("object : %s  \n equation : %s" % (node_object, equation))
  #     eq_ID, var_ID = self.match_node_equation_inverse[equation]
  #     self.node_arc_associations[nw_str_ID]["nodes"][node_object] = (eq_ID, var_ID)
  #   print("debugging -- wait")

  # def matchArcReceiver(self, selection):
  #   print("match receiver -- selection", selection)
  #   nw_str_ID = self.radio_InterNetworks.getStrID()
  #   for arc_object, equation in selection:
  #     print("object : %s  \n equation : %s" % (arc_object, equation))
  #     eq_ID, var_ID = self.match_arc_equation_inverse[equation]
  #     self.node_arc_associations[nw_str_ID]["arcs"][arc_object] = (eq_ID, var_ID)
  #   print("debugging -- wait")

  def __makeVariablesToBeValueInitialised(self, entity_object_str):
    # find the ID for the "value" variable
    numerical_value = self.ontology_container.rules["numerical_value"]
    var_ID_value = -1
    variables = self.ontology_container.variables
    for var_ID in variables:
      if variables[var_ID]["label"] == numerical_value:
        var_ID_value = var_ID
        break
    if var_ID_value == -1:
      print("Error -- did not fined variable for numerical value")
    # find all those expressions that ask for a value
    # print("debugging -- ", dir(self.entity_behaviours[entity_object_str]))
    behaviour = self.entity_behaviours[entity_object_str]
    tree = behaviour["tree"]
    a = walkDepthFirstFnc(tree, 0)
    to_be_initialised = set()
    for ID in a:
      _ID = behaviour["nodes"][ID]
      lbl, varStrID = _ID.split("_")
      if lbl != "equation":
        varID = int(varStrID)

        var = self.ontology_container.variables[varID]
        equations = var["equations"]
        for e in equations:
          eq = equations[e]["rhs"]
          if isVariableInExpression(eq, var_ID_value):
            # print("debugging -- variable ", var["label"], eq)
            to_be_initialised.add(varID)

    self.entity_behaviours[entity_object_str]["to_be_initialised"] = sorted(to_be_initialised)
    # print("debugging -- to be initialised", sorted(to_be_initialised))

  # =============================

  def analyseBiPartiteGraph(self, entity, var_ID, blocked):
    var_equ_tree_graph, assignments = AnalyseBiPartiteGraph(var_ID,
                                                            self.ontology_container,
                                                            self.ontology_name,
                                                            blocked,
                                                            entity)

    # self.__makeLatexDocument(entity, assignments)
    return var_equ_tree_graph, assignments

  def __makeLatexDocument(self, obj, assignments):
    # obj = self.__makeCurrentObjectString()
    file_name = obj.replace("|", "__").replace(".", "_").replace(" ", "_")
    makeLatexDoc(file_name, assignments, self.ontology_container)

  def __askForNewVariantName(self, limiting_list):
    dialoge = UI_String("Provide a new variant name", placeholdertext="variant", limiting_list=limiting_list)
    dialoge.exec_()
    variant = dialoge.getText()
    del dialoge
    return variant

  def __makeCurrentObjectString(self):
    component = self.node_arc.strip("s")
    object_string = TEMPLATE_ENTITY_OBJECT % (
            self.selected_InterNetwork_strID, component, self.selected_object, self.selected_variant_str_ID)
    if object_string not in self.entity_behaviours:
      self.entity_behaviours[object_string] = None
    return object_string

  def __makeAndDisplayEquationListLeftAndRight(self):

    entity_str_ID = self.__makeCurrentObjectString()
    try:
      if self.state == "new_variant":
        # print("debugging -- new variant, entity string", entity_str_ID)
        if "base" in entity_str_ID:
          pass
          # print("debugging -- found D-D", entity_str_ID)

      self.selected_base_variable = self.entity_behaviours.getRootVariableID(entity_str_ID)
      if not self.selected_base_variable:
        return
      equation_ID_list = self.entity_behaviours.getEquationIDList(entity_str_ID)
      blocked_ = self.entity_behaviours.getBlocked(entity_str_ID)  # ok that is a copy
      blocked = deepcopy(blocked_)
      root_equation = equation_ID_list.pop(0)

      root_eq_ID = self.equation_inverse_index[root_equation]  # RULE: single equation
      eq_ID, var_ID, var_type, nw_eq, equation_label = self.equation_information[root_eq_ID]

      self.__makeEquationTextButton(equation_label, self.ui.pushButtonLeft, "click to accept")

      # print("debugging -- left list showing ", equation_ID_list[0:5])

      equation_ID_set = set()
      [equation_ID_set.add(e) for e in equation_ID_list]
      block_set = set()
      [block_set.add(e) for e in blocked]
      left_eqs = list(equation_ID_set - block_set)
      self.leftListEquationIDs = left_eqs

      self.leftIndex = self.__makeLeftRightList(left_eqs, self.ui.listLeft)
      self.rightIndex = self.__makeLeftRightList(blocked, self.ui.listRight)
      self.rightListEquationIDs = deepcopy(blocked)
    except:
      self.entity_behaviours.removeVariant(entity_str_ID)

  def __makeLeftRightList(self, eq_list, ui):
    label_list = []
    index = {}
    count = 0
    for id in eq_list:
      e_ID = self.equation_inverse_index[id]
      eq_ID, var_ID, var_type, nw_eq, equation_label = self.equation_information[e_ID]
      # label = "%s>%s>   %s" % (var_ID, eq_ID, equation_label)
      index[count] = (var_ID, eq_ID)
      count += 1
      label_list.append(equation_label)
    ui.clear()
    ui.addItems(label_list)
    return index

  def __makeEntityObjectStrID(self):
    nw_str_ID = self.radio_InterNetworks.label_indices[self.selected_InterNetwork_ID]
    entity_label_ID = self.radio_Entities.label_indices[self.selected_Entity_ID]
    variant = self.radio_Variants.getStrID()  # label_indices[self.radio_Variants.getStrID()] #selected_variant_ID]
    entity_object_str = functionMakeObjectStringID(nw_str_ID, entity_label_ID, variant)
    return entity_object_str

  def __makeRightSelector(self):
    show = self.rightListEquationIDs
    equation_list, index = self.__makeRadioSelectorLists(show)
    self.radio_Right.makeSelector(pixel_or_text, equation_list, self.layout_Right)
    self.equation_right_clean = False
    self.current_right_index = index

  def __makeDuplicateShows(self):
    # nw = self.selected_InterNetwork_ID
    # entity = self.selected_Entity_ID
    # variant = self.selected_variant_ID
    entity_object_str = self.__makeCurrentObjectString()

    nodes = self.entity_behaviours[entity_object_str]["nodes"]
    blocked = self.entity_behaviours[entity_object_str]["blocked"]
    show = []
    # select duplicates:
    for node in nodes:
      label, str_ID = nodes[node].split("_")
      ID = int(str_ID)
      if label == "variable":
        equation_IDs = sorted(self.ontology_container.variables[ID]["equations"])
        if len(equation_IDs) > 1:
          # print("debugging -- found variable %s"%equation_IDs)
          show.extend(equation_IDs)
    for eq_ID in blocked:
      if eq_ID in show:
        show.remove(eq_ID)
    return show

  def __makeEquationTextButton(self, text, button, tooltip):
    button.setText(text)
    button.setToolTip(tooltip)
    button.show()

  def __makeEquationPixelButton(self, equation_label, button, tooltip):
    button.setText("")
    icon, label, size = equation_label
    button.setIcon(icon)
    button.setIconSize(size)
    button.setToolTip(tooltip)
    button.show()
    return

  def __makeBase(self):

    # print("debugging -- define base")
    self.ui.pushButtonLeft.setText('')
    self.ui.pushButtonLeft.hide()
    self.ui.groupBoxControls.show()

    self.setState("make_base")
    self.selected_variant = "base"
    nw = self.selected_InterNetwork_strID

    rules_selector = UI_TwoListSelector()
    rules_selector.setWindowTitle("chose a list of variable classes")
    rules_selector.setToolTip("we show only those variable types that have equations")
    # Rule: this is being tightened now one can only choose variable types that have equations
    self.rules[nw] = self.ontology_container.variable_types_on_networks[nw]
    variable_equation_list, variable_types_having_equations = self.__makeEquationList_per_variable_type()

    rules_selector.populateLists(variable_types_having_equations,
                                 [])  # self.ontology_container.variable_types_on_networks[nw], [])
    rules_selector.exec_()
    selection = rules_selector.getSelected()
    if not selection:
      return
    self.rules[nw] = rules_selector.getSelected()

    self.variable_equation_list, variable_types_having_equations = self.__makeEquationList_per_variable_type()

    left_equations = self.variable_equation_list[self.selected_InterNetwork_strID][
      self.node_arc]  # self.variable_equation_list[self.selected_InterNetwork_strID][self.node_arc]
    self.leftIndex = self.__makeLeftRightList(left_equations, self.ui.listLeft)
    self.status_report("making base for %s" % self.selected_Entity_ID)
    self.selected_variant = None
    self.__makeAndDisplayEquationListLeftAndRight()

  def __makeEquationList_per_variable_type(self):

    variable_equation_list = {}
    nw = self.selected_InterNetwork_strID
    variable_types_having_equations = set()

    for e in self.equation_information:
      eq_ID, var_ID, var_type, nw_eq, equation_label = self.equation_information[e]
      nws = list(self.ontology_container.ontology_tree[nw]["parents"])
      nws.append(nw)

      for i_nw in nws:
        if nw not in variable_equation_list:
          variable_equation_list[nw] = {}
          variable_equation_list[nw]["nodes"] = []
          variable_equation_list[nw]["arcs"] = []

        for i_var_type in self.rules[self.selected_InterNetwork_strID]:
          if i_nw == nw_eq and i_var_type in var_type:
            variable_equation_list[nw][self.node_arc].append(eq_ID)
            variable_types_having_equations.add(var_type)

    return variable_equation_list, variable_types_having_equations

  def __makeVariantStringList(self):

    nw_str_ID = self.selected_InterNetwork_strID
    current_component = self.node_arc.strip("s")
    object = self.selected_object
    entity_str_IDs = sorted(self.entity_behaviours)
    variants = set()
    for o in entity_str_IDs:
      network, component, entity, variant = functionGetObjectsFromObjectStringID(o)
      if network == nw_str_ID and current_component == component and entity == object:
        if self.entity_behaviours[o]:
          variants.add(variant)
    #
    # self.ui.listVariants.clear()
    # self.ui.listVariants.addItems(list(variants))
    return sorted(variants)

  def __makeVariantRadioIDList(self):

    variant_list = self.entity_behaviours.getVariantList(self.selected_InterNetwork_strID, self.selected_object)
    self.ui.listVariants.clear()
    self.ui.listVariants.addItems(variant_list)

    return

  def __makeRadioSelectorLists(self, selector_list):

    radio_selectors = {
            "rendered": [],
            "pixelled": []
            }

    index = {"variable": [], "equation": []}
    indices = []

    for equ_ID in selector_list:
      var_ID, var_type, nw_eq, rendered_equation, pixelled_equation = self.equations[equ_ID]
      radio_selectors["rendered"].append(rendered_equation)
      radio_selectors["pixelled"].append(pixelled_equation)
      indices.append(equ_ID)

    return radio_selectors, indices

  def __makeEquationAndIndexLists(self):
    """
    equations : list of equation IDs
    equation_information : dictionary of tuples
          eq_ID, var_ID, var_type, nw_eq, equation_label
    """
    # TODO: drop pixel version and use info being generated in the ontology_container

    equations = []
    equation_information = {}
    equation_inverse_index = {}
    equation_variable_dictionary = self.ontology_container.equation_variable_dictionary
    count = -1
    for eq_ID in equation_variable_dictionary:
      count += 1
      var_ID, equation = equation_variable_dictionary[eq_ID]
      var_type = self.ontology_container.variables[var_ID]["type"]
      nw_eq = self.ontology_container.variables[var_ID]["network"]

      if pixel_or_text == "text":

        rendered_expressions = renderExpressionFromGlobalIDToInternal(
                equation["rhs"],
                self.ontology_container.variables,
                self.ontology_container.indices)

        rendered_variable = self.ontology_container.variables[var_ID]["aliases"]["internal_code"]
        equation_label = "%s := %s" % (rendered_variable, rendered_expressions)
      elif pixel_or_text == "pixelled":
        equation_label = self.__make_icon(eq_ID)

      # equations[eq_ID] = (var_ID, var_type, nw_eq, rendered_equation, pixelled_equation)
      equations.append(equation_label)
      equation_inverse_index[eq_ID] = count
      equation_information[count] = (eq_ID, var_ID, var_type, nw_eq, equation_label)
    return equations, equation_information, equation_inverse_index

  # def __makeEquationList_keep_not_used(self):
  #
  #   equations = {}  # tuple
  #   equation_variable_dictionary = self.ontology_container.equation_variable_dictionary
  #   for eq_ID in equation_variable_dictionary:
  #     var_ID, equation = equation_variable_dictionary[eq_ID]
  #     var_type = self.ontology_container.variables[var_ID]["type"]
  #     nw_eq = self.ontology_container.variables[var_ID]["network"]
  #
  #     rendered_expressions = renderExpressionFromGlobalIDToInternal(
  #             equation["rhs"],
  #             self.ontology_container.variables,
  #             self.ontology_container.indices)
  #
  #     rendered_variable = self.ontology_container.variables[var_ID]["aliases"]["internal_code"]
  #     rendered_equation = "%s := %s" % (rendered_variable, rendered_expressions)
  #     pixelled_equation = self.__make_icon(eq_ID)
  #
  #     equations[eq_ID] = (var_ID, var_type, nw_eq, rendered_equation, pixelled_equation)
  #
  #   return equations
  #
  # def __make_icon(self, eq_ID):
  #
  #   template = join(self.location, "equation_%s.png")
  #   f = template % eq_ID
  #   label = QtWidgets.QLabel()
  #   pix = QtGui.QPixmap(f)
  #   icon = QtGui.QIcon(pix)
  #   size = pix.size()
  #   return icon, label, size
