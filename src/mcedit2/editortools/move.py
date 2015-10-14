"""
    move
"""
from __future__ import absolute_import, division, print_function

import logging

from PySide import QtGui

from mcedit2.command import SimpleRevisionCommand
from mcedit2.editortools import EditorTool
from mcedit2.imports import PendingImportNode, PendingImport
from mcedit2.rendering.scenegraph import scenenode
from mcedit2.util.showprogress import showProgress
from mcedit2.widgets.coord_widget import CoordinateWidget
from mcedit2.widgets.layout import Column
from mcedit2.widgets.rotation_widget import RotationWidget
from mceditlib.export import extractSchematicFromIter
from mceditlib.selection import BoundingBox

log = logging.getLogger(__name__)


class MoveSelectionCommand(SimpleRevisionCommand):
    def __init__(self, moveTool, pendingImport, text=None, *args, **kwargs):
        if text is None:
            text = moveTool.tr("Move Selected Object")
        super(MoveSelectionCommand, self).__init__(moveTool.editorSession, text, *args, **kwargs)
        self.pendingImport = pendingImport
        self.moveTool = moveTool

    def undo(self):
        super(MoveSelectionCommand, self).undo()
        self.moveTool.currentImport = None
        #self.moveTool.removePendingImport(self.pendingImport)
        self.moveTool.editorSession.chooseTool("Select")

    def redo(self):
        self.moveTool.currentImport = self.pendingImport
        #self.moveTool.addPendingImport(self.pendingImport)
        self.moveTool.editorSession.chooseTool("Move")
        super(MoveSelectionCommand, self).redo()


class MoveOffsetCommand(QtGui.QUndoCommand):
    def __init__(self, oldPoint, newPoint, pendingImport):
        super(MoveOffsetCommand, self).__init__()
        self.pendingImport = pendingImport
        self.setText(QtGui.qApp.tr("Move Object"))
        self.newPoint = newPoint
        self.oldPoint = oldPoint

    def undo(self):
        self.pendingImport.basePosition = self.oldPoint

    def redo(self):
        self.pendingImport.basePosition = self.newPoint


class MoveRotateCommand(QtGui.QUndoCommand):
    def __init__(self, oldRotation, newRotation, pendingImport):
        super(MoveRotateCommand, self).__init__()
        self.pendingImport = pendingImport
        self.setText(QtGui.qApp.tr("Rotate Object"))
        self.newRotation = newRotation
        self.oldRotation = oldRotation

    def undo(self):
        self.pendingImport.rotation = self.oldRotation

    def redo(self):
        self.pendingImport.rotation = self.newRotation


class MoveFinishCommand(SimpleRevisionCommand):
    def __init__(self, moveTool, pendingImport, *args, **kwargs):
        super(MoveFinishCommand, self).__init__(moveTool.editorSession, moveTool.tr("Finish Move"), *args, **kwargs)
        self.pendingImport = pendingImport
        self.moveTool = moveTool
        self.previousSelection = None

    def undo(self):
        super(MoveFinishCommand, self).undo()
        #self.moveTool.addPendingImport(self.pendingImport)
        self.moveTool.currentImport = self.pendingImport
        self.editorSession.currentSelection = self.previousSelection
        self.editorSession.chooseTool("Move")

    def redo(self):
        super(MoveFinishCommand, self).redo()
        self.previousSelection = self.editorSession.currentSelection
        self.editorSession.currentSelection = self.pendingImport.importBounds
        self.moveTool.currentImport = None
        #self.moveTool.removePendingImport(self.pendingImport)
        self.editorSession.chooseTool("Select")


class MoveTool(EditorTool):
    iconName = "move"
    name = "Move"

    def __init__(self, editorSession, *args, **kwargs):
        super(MoveTool, self).__init__(editorSession, *args, **kwargs)
        self.overlayNode = scenenode.Node()
        self._currentImport = None
        self._currentImportNode = None

        self.toolWidget = QtGui.QWidget()

        self.pointInput = CoordinateWidget()
        self.pointInput.pointChanged.connect(self.pointInputChanged)

        self.rotationInput = RotationWidget()
        self.rotationInput.rotationChanged.connect(self.rotationChanged)

        self.copyOptionsWidget = QtGui.QGroupBox(self.tr("Options"))

        self.copyAirCheckbox = QtGui.QCheckBox(self.tr("Copy Air"))
        self.copyOptionsWidget.setLayout(Column(self.copyAirCheckbox))

        confirmButton = QtGui.QPushButton("Confirm")  # xxxx should be in worldview
        confirmButton.clicked.connect(self.confirmImport)
        self.toolWidget.setLayout(Column(self.pointInput,
                                         self.rotationInput,
                                         self.copyOptionsWidget,
                                         confirmButton,
                                         None))

    def rotationChanged(self, rots, live):
        if self.currentImport:
            if live:
                self.currentImportNode.setPreviewRotation(rots)
            else:
                command = MoveRotateCommand(self.currentImport.rotation, rots, self.currentImport)
                self.editorSession.pushCommand(command)

            self.editorSession.updateView()

    def pointInputChanged(self, value):
        if value is not None:
            self.importDidMove(value, self.currentImport.basePosition)

    # --- Pending imports ---

    def importDidMove(self, newPoint, oldPoint):
        if newPoint != oldPoint:
            command = MoveOffsetCommand(oldPoint, newPoint, self.currentImport)
            self.editorSession.pushCommand(command)

    @property
    def currentImport(self):
        return self._currentImport

    @currentImport.setter
    def currentImport(self, pendingImport):
        self._currentImport = pendingImport
        self.pointInput.setEnabled(pendingImport is not None)
        # Set current import to different color?
        # for node in self.pendingImportNodes.itervalues():
        #     node.outlineNode.wireColor = (.2, 1., .2, .5) if node.pendingImport is value else (1, 1, 1, .3)
        if pendingImport is None:
            if self._currentImportNode is not None:
                self.overlayNode.removeChild(self._currentImportNode)
                self._currentImportNode = None
        else:
            node = PendingImportNode(pendingImport, self.editorSession.textureAtlas)
            node.importMoved.connect(self.importDidMove)
            self._currentImportNode = node
            self.overlayNode.addChild(node)
            self.rotationInput.rotation = pendingImport.rotation

    @property
    def currentImportNode(self):
        return self._currentImportNode

    # --- Mouse events ---

    def mouseMove(self, event):
        # Hilite face cursor is over
        if self.currentImport is not None:
            self.currentImportNode.mouseMove(event)

        # Highlight face of box to move along, or else axis pointers to grab and drag?

    def mouseDrag(self, event):
        self.mouseMove(event)

    def mousePress(self, event):
        if self.currentImport is not None:
            self.currentImportNode.mousePress(event)

    def mouseRelease(self, event):
        if self.currentImport is not None:
            self.currentImportNode.mouseRelease(event)

    # --- Editor events ---

    def toolActive(self):
        self.editorSession.selectionTool.hideSelectionWalls = True
        if self.currentImport is None:
            self.rotationInput.rotation = (0, 0, 0)
            if self.editorSession.currentSelection is None:
                return

            # This makes a reference to the latest revision in the editor.
            # If the moved area is changed between "Move" and "Confirm", the changed
            # blocks will be moved.
            pos = self.editorSession.currentSelection.origin
            pendingImport = PendingImport(self.editorSession.currentDimension, pos,
                                          self.editorSession.currentSelection,
                                          self.tr("<Moved Object>"),
                                          isMove=True)
            moveCommand = MoveSelectionCommand(self, pendingImport)

            self.editorSession.pushCommand(moveCommand)

    def toolInactive(self):
        self.editorSession.selectionTool.hideSelectionWalls = False
        # hide hovers for box handles?

    def confirmImport(self):
        if self.currentImport is None:
            return

        command = MoveFinishCommand(self, self.currentImport)
        destDim = self.editorSession.currentDimension
        with command.begin():
            log.info("Move: starting")
            sourceDim, selection = self.currentImport.getSourceForDim(destDim)

            # Copy to destination
            log.info("Move: copying")
            task = destDim.copyBlocksIter(sourceDim, selection,
                                          self.currentImport.importPos,
                                          biomes=True, create=True,
                                          copyAir=self.copyAirCheckbox.isChecked())

            showProgress(self.tr("Pasting..."), task)

            log.info("Move: clearing")
            # Clear source
            if self.currentImport.isMove:
                fill = destDim.fillBlocksIter(self.currentImport.selection, "air")
                showProgress(self.tr("Clearing..."), fill)

        self.editorSession.pushCommand(command)
