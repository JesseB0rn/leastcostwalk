# -*- coding: utf-8 -*-

"""
/***************************************************************************
 LeastCostWalk
                                 A QGIS plugin
 This plugins findst the east cost path with uphill/downhill/traverse time cost
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2024-06-30
        copyright            : (C) 2024 by Jesse Born
        email                : jesse.born@gmx.ch
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

__author__ = 'Jesse Born'
__date__ = '2024-06-30'
__copyright__ = '(C) 2024 by Jesse Born, Alte Kanti Aarau'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsWkbTypes,
                       QgsFeatureSink,
                       QgsGeometry,
                       QgsFeature,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterPoint,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingException,
                       QgsProcessingParameterNumber,
                       QgsProcessingFeedback,
                       QgsProcessingParameterCrs,
                       QgsProcessingContext,
                       QgsRectangle,
                       QgsProject,
                       QgsField,
                       QgsPointXY,
                       QgsCoordinateReferenceSystem,
                       QgsPoint,
                       QgsCoordinateTransform,
                       QgsFields,
                       QgsMapLayerType)
import queue
from math import sqrt

SQRT2 = sqrt(2)

class LeastCostWalkAlgorithm(QgsProcessingAlgorithm):
    """

    """

    FLOAT_UPHILL_COST_COEFF = "FLOAT_UPHILL_COEFF"
    FLOAT_STEEP_UPHILL_COST_COEFF = "FLOAT_STEEP_UPHILL_COEFF"
    FLOAT_DOWNHILL_COST_COEFF = "FLOAT_DOWNHILL_COEFF"
    FLOAT_STEEP_DOWNHILL_COST_COEFF = "FLOAT_STEEP_DOWNHILL_COEFF"
    FLOAT_FLAT_COST_COEFF = "FLOAT_FLAT_COEFF"
    FLOAT_COST_COEFF = "FLOAT_COST_COEFF"

    INPUT_COST_RASTER = 'INPUT_COST_RASTER'
    INPUT_ELEV_RASTER = 'INPUT_ELEV_RASTER'

    INPUT_START_POINT = 'INPUT_START_POINT'
    INPUT_END_POINT = 'INPUT_END_POINT'

    POINTS_CRS = 'POINTS_CRS'

    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # Raster layers

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_COST_RASTER,
                self.tr('Input Cost Raster')
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_ELEV_RASTER,
                self.tr('Input Elevation Raster')
            )
        )

        # Points

        self.addParameter(
            QgsProcessingParameterPoint(
                self.INPUT_START_POINT,
                self.tr('Start Point')
            )
        )
        self.addParameter(
            QgsProcessingParameterPoint(
                self.INPUT_END_POINT,
                self.tr('End Point')
            )
        )

        self.addParameter(
            QgsProcessingParameterCrs(self.POINTS_CRS, self.tr('Input Points CRS'))
        )

        # Coefficients

        self.addParameter(
            QgsProcessingParameterNumber(
                self.FLOAT_COST_COEFF,
                self.tr("Cost Matrix Scaling Coefficient"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.04
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.FLOAT_UPHILL_COST_COEFF,
                self.tr("Uphill Cost Coeff"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0025
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.FLOAT_STEEP_UPHILL_COST_COEFF,
                self.tr("Steep Uphill Cost Coeff"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=2.0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.FLOAT_DOWNHILL_COST_COEFF,
                self.tr("Downhill Cost Coeff"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.00125
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.FLOAT_STEEP_DOWNHILL_COST_COEFF,
                self.tr("Steep Downhill Cost Coeff"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=2.0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.FLOAT_FLAT_COST_COEFF,
                self.tr("Flat Cost Coeff"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.00025
            )
        )

        # Output
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Output Walked Path')
            )
        )

    def parseParams(self, parameters, context: QgsProcessingContext):
        self.cost_raster = self.parameterAsRasterLayer(parameters, self.INPUT_COST_RASTER, context)
        self.elev_raster = self.parameterAsRasterLayer(parameters, self.INPUT_ELEV_RASTER, context)

        self.startpoitn = self.parameterAsPoint(parameters, self.INPUT_START_POINT, context)
        self.endpoint = self.parameterAsPoint(parameters, self.INPUT_END_POINT, context)

        self.coeffs = [
            self.parameterAsDouble(parameters, self.FLOAT_COST_COEFF, context),
            self.parameterAsDouble(parameters, self.FLOAT_DOWNHILL_COST_COEFF, context),
            self.parameterAsDouble(parameters, self.FLOAT_STEEP_DOWNHILL_COST_COEFF, context),
            self.parameterAsDouble(parameters, self.FLOAT_UPHILL_COST_COEFF, context),
            self.parameterAsDouble(parameters, self.FLOAT_STEEP_UPHILL_COST_COEFF, context),
            self.parameterAsDouble(parameters, self.FLOAT_FLAT_COST_COEFF, context)
        ]
        if self.cost_raster is None or self.elev_raster is None or self.startpoitn is None or self.endpoint is None:
            raise QgsProcessingException(self.tr("One or more required params missing / broken / malformed"))

        if self.cost_raster.crs() != self.elev_raster.crs():
            raise QgsProcessingException(self.tr("cost and elevation layer crs mismatch"))

        if self.cost_raster.rasterUnitsPerPixelX() != self.elev_raster.rasterUnitsPerPixelX() or self.cost_raster.rasterUnitsPerPixelY() != self.elev_raster.rasterUnitsPerPixelY():
            raise QgsProcessingException(self.tr("cost and elevation layer resolution mismatch"))
        
        inputPointsCRS = self.parameterAsCrs(parameters, self.POINTS_CRS, context)
        xform = QgsCoordinateTransform(inputPointsCRS, self.cost_raster.crs(), QgsProject.instance())

        self.startpoitn = xform.transform(self.startpoitn)
        self.endpoint = xform.transform(self.endpoint)

    def _pointToRC(self, point: QgsPointXY):
        return (int(point.x() / self.xres), int(point.y() / self.yres))

    def _rcToPointXY(self, rowcol: tuple[int, int]):
        row, col = rowcol
        p = QgsPointXY()
        p.set(row * self.xres + self.cell_offset_x, col * self.yres + self.cell_offset_y)
        return p

    def _rcToPoint(self, rowcol: tuple[int, int]):
        return QgsPoint((rowcol[0] + 0.5) * self.xres, (rowcol[1] + 0.5) * self.yres)

    def _manhattan(self, a_rc: tuple[int, int], b_rc: tuple[int, int]):
        return abs(a_rc[0] - b_rc[0]) + abs(a_rc[1] - b_rc[1])

    def _prepare_RC_bounds(self, extent: QgsRectangle):
        self.x_min = self.cost_raster.extent().xMinimum() / self.xres
        self.x_max = self.cost_raster.extent().xMaximum() / self.yres
        self.y_min = self.cost_raster.extent().yMinimum() / self.xres
        self.y_max = self.cost_raster.extent().yMaximum() / self.yres

    def _neighbor_valid(self, xy):
        x, y = xy
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    def _neighbors(self, rc) -> list[tuple[int, int]]:
        x, y = rc
        results = [(x + 1, y),      (x, y - 1),     (x - 1, y), 
                   (x, y + 1),                      (x + 1, y - 1), 
                   (x + 1, y + 1),  (x - 1, y - 1), (x - 1, y + 1)]
        results = list(filter(self._neighbor_valid, results))
        return results

    def cost(self, a_rc: tuple[int, int], b_rc: tuple[int, int]):
        """
        Computes edge cost between two raster cells (friction + elevation gain/loss)
        """
        h_dist = SQRT2 if a_rc[0] != b_rc[0] or a_rc[1] != b_rc[1] else 1.0
        a, b = self._rcToPointXY(a_rc), self._rcToPointXY(b_rc)

        frictionSampleA = self.cost_provider.sample(a, 1)
        frictionSampleB = self.cost_provider.sample(b, 1)

        elevSampleA = self.elev_provider.sample(a, 1)
        elevSampleB = self.elev_provider.sample(b, 1)

        frictionA = frictionSampleA[0] if frictionSampleA[1] else float('inf')
        frictionB = frictionSampleB[0] if frictionSampleB[1] else float('inf')

        friction_cost = (frictionA[0] + frictionB[0]) / 2
        climb = min(elevSampleB[0] - elevSampleA[0], 0.0)
        dive = max(elevSampleA[0] - elevSampleB[0], 0.0)

        is_steep = climb / h_dist*self.xres >= 0.70 or dive / h_dist*self.xres >= 1.19
        time_cost = climb * (self.coeffs[4] if is_steep else self.coeffs[3]) + dive * (self.coeffs[2] if is_steep else self.coeffs[1]) + h_dist * self.coeffs[5]

        return friction_cost * self.coeffs[0] * h_dist + time_cost

    def heuristic(self, a_rc: tuple[int, int], b_rc: tuple[int, int]):
        """
        Heuristic function for A*: estimate of the cost from a to b
        """
        return self._manhattan(a_rc, b_rc)

    def processAlgorithm(self, parameters, context: QgsProcessingContext, feedback: QgsProcessingFeedback):
        """
        Here is where the processing itself takes place.
        """
        self.parseParams(parameters, context)

        self.xres, self.yres = self.cost_raster.rasterUnitsPerPixelX(), self.cost_raster.rasterUnitsPerPixelY()
        self.cell_offset_x, self.cell_offset_y = self.xres / 2, self.yres / 2
        feedback.pushInfo(self.tr(f"Units per px x: {self.xres} y: {self.yres}"))

        self._prepare_RC_bounds(self.cost_raster.extent().intersect(self.elev_raster.extent()))

        self.cost_provider = self.cost_raster.dataProvider()
        self.elev_provider = self.elev_raster.dataProvider()  

        self.startpoitn = self._rcToPointXY(cell_start_xy := self._pointToRC(self.startpoitn))
        self.endpoint = self._rcToPointXY(cell_end_xy := self._pointToRC(self.endpoint))

        self.max_manhattan = self._manhattan(cell_start_xy, cell_end_xy)
        
        feedback.pushInfo(self.tr(f"start cell: {cell_start_xy[0]}, {cell_start_xy[1]}"))
        feedback.pushInfo(self.tr(f"max manhattan exploration depth: {self.max_manhattan}"))

        if not (self._neighbor_valid(cell_start_xy) and self._neighbor_valid(cell_end_xy)):
            raise QgsProcessingException(self.tr("😬 Start or endpoint outside raster extent"))
        # setup

        frnt = queue.PriorityQueue()
        came_from_cost = dict()

        came_from_cost[cell_start_xy] = (None, 0)
        decided_nodes = set()
        frnt.put((0, cell_start_xy))


        # A*
        result = None

        while frnt.qsize() > 0:
            _, current_node = frnt.get()
            if current_node in decided_nodes:
                continue
            decided_nodes.add(current_node)

            if current_node == cell_end_xy:
                feedback.pushInfo(self.tr("Found path"))

                path = []
                costs = []
                tn = current_node
                while tn is not None:
                    path.append(tn)
                    costs.append(came_from_cost[tn][1])
                    tn = came_from_cost[tn][0]
                if len(path) == 1:
                    path += [cell_start_xy]
                    costs += [0.0]
                costs.reverse()
                path.reverse()
                result = (path, costs)
                break
            
            for ngb in self._neighbors(current_node):
                new_cost = came_from_cost[current_node][1] + self.cost(current_node, ngb)
                if ngb not in came_from_cost or new_cost < came_from_cost[ngb][1]:
                    came_from_cost[ngb] = (current_node, new_cost)
                    priority = new_cost + self.heuristic(ngb, cell_end_xy) / self.max_manhattan
                    frnt.put((priority, ngb))

            if feedback.isCanceled():
                raise KeyboardInterrupt("Algorithm was cancelled")
            # feedback.setProgress(self._manhattan(cell_end_xy, current_node) / self.max_manhattan * 100)
        # feedback.pushInfo(self.tr("%f" % provider.sample(self.startpoitn, 1)[0]))
        points = [self._rcToPoint(node) for node, cost in zip(result[0], result[1])]

        sink_fields = LeastCostWalkHelper.create_fields()
        (sink, dest_id) = self.parameterAsSink(parameters, self.OUTPUT, context, sink_fields, QgsWkbTypes.LineString, self.cost_raster.crs())
        sink.addFeature(LeastCostWalkHelper.create_path_feature_from_points(points, sink_fields))

        return {self.OUTPUT: dest_id}

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'LeastCostWalk'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr(self.name())

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return self.tr(self.groupId())

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'LeastCostWalk'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        # return string

    def createInstance(self):
        return LeastCostWalkAlgorithm()

class LeastCostWalkHelper:
    @staticmethod
    def create_fields():
        # start_field = QgsField("start point id", QVariant.Int, "int")
        # end_field = QgsField("end point id", QVariant.Int, "int")
        # cost_field = QgsField("total cost", QVariant.Double, "double", 10, 3)
        fields = QgsFields()
        # fields.append(start_field)
        # fields.append(end_field)
        # fields.append(cost_field)
        return fields
    @staticmethod
    def create_path_feature_from_points(path_points, fields):
        polyline = QgsGeometry.fromPolyline(path_points)
        feature = QgsFeature(fields)
        # feature.setAttribute(0, 1) # id
        # start_index = feature.fieldNameIndex("start point id")
        # end_index = feature.fieldNameIndex("end point id")
        # cost_index = feature.fieldNameIndex("total cost")
        # feature.setAttribute(start_index, attr_vals[0])
        # feature.setAttribute(end_index, attr_vals[1])
        # feature.setAttribute(cost_index, attr_vals[2])  # cost
        feature.setGeometry(polyline)
        return feature
