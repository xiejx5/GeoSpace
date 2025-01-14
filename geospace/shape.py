import os
import numpy as np
from osgeo import ogr
from geospace._const import WGS84
from geospace.utils import rep_file
from geospace.projection import read_srs, coord_trans


def shp_buffer(in_shp, out_shp, buffdist, in_srs=None):
    return shp_geom_map(in_shp, out_shp, in_srs=in_srs,
                        func=lambda geom: geom.Buffer(float(buffdist)))


def shp_projection(in_shp, out_shp, in_srs=WGS84, out_srs=WGS84):
    # Filename of input OGR file
    if isinstance(in_shp, ogr.Layer):
        inLayer = in_shp
    else:
        source_ds = ogr.Open(in_shp)
        inLayer = source_ds.GetLayer()

    # input SpatialReference
    inSpatialRef = read_srs([inLayer, in_srs])

    # output SpatialReference
    outSpatialRef = read_srs(out_srs)

    # create the CoordinateTransformation
    coordTrans = coord_trans(inSpatialRef, outSpatialRef)

    def transform(geom):
        geom.Transform(coordTrans)
        return geom

    return shp_geom_map(in_shp, out_shp, out_srs=outSpatialRef, func=transform)


def shp_filter(shps, filter_sql, filter_shp=None):
    import re

    driver = ogr.GetDriverByName("ESRI Shapefile")
    ds_shp = ogr.Open(shps, 0)
    layer = ds_shp.GetLayer()
    if filter_shp is None:
        filter_shp = '/vsimem/filter.shp'

    # select by indexes in gs.basin_average when field is None
    res = re.findall(r"None = '([0-9]+)'", filter_sql)
    if len(res) > 0:
        return shp_geom_map(layer, filter_shp, idxs=int(res[0]))

    layer.SetAttributeFilter(filter_sql)
    filter = driver.CreateDataSource(filter_shp)
    filter.CopyLayer(layer, 'filter')
    return filter_shp


def shp_geom_map(in_shp, out_shp, idxs=None, func=None,
                 in_srs=None, out_srs=None):
    # Filename of input OGR file
    driver = ogr.GetDriverByName("ESRI Shapefile")
    if isinstance(in_shp, ogr.Layer):
        inLayer = in_shp
    else:
        source_ds = ogr.Open(in_shp)
        inLayer = source_ds.GetLayer()

    # output SpatialReference
    outSpatialRef = read_srs([out_srs, inLayer, in_srs])

    # create the output layer
    if 'vsimem' not in os.path.dirname(out_shp):
        if (not os.path.exists(os.path.dirname(out_shp)) and
                os.path.dirname(out_shp) != ''):
            os.makedirs(os.path.dirname(out_shp))
    if os.path.exists(out_shp):
        driver.DeleteDataSource(out_shp)
    outDataSet = driver.CreateDataSource(out_shp)
    outLayer = outDataSet.CreateLayer(out_shp, outSpatialRef)

    # add fields
    inLayerDefn = inLayer.GetLayerDefn()
    for i in range(0, inLayerDefn.GetFieldCount()):
        fieldDefn = inLayerDefn.GetFieldDefn(i)
        outLayer.CreateField(fieldDefn)

    # get the output layer's feature definition
    outLayerDefn = outLayer.GetLayerDefn()

    # set all feature idxs if not assigned
    if idxs is None:
        idxs = range(inLayer.GetFeatureCount())
    elif isinstance(idxs, int):
        idxs = [idxs]

    # loop through the input features
    for i in idxs:
        inFeature = inLayer.GetFeature(i)
        # get the input geometry
        geom = inFeature.GetGeometryRef()
        # create a new feature
        outFeature = ogr.Feature(outLayerDefn)
        # set the geometry and attribute
        outFeature.SetGeometry(geom if func is None else func(geom))
        for j in range(0, outLayerDefn.GetFieldCount()):
            outFeature.SetField(outLayerDefn.GetFieldDefn(
                j).GetNameRef(), inFeature.GetField(j))
        # add the feature to the shapefile
        outLayer.CreateFeature(outFeature)
        # dereference the features and get the next input feature
        outFeature = None

    return out_shp


def shp_weighted_mean(in_shp, clip_shp, field, out_shp=None, save_cache=False):
    driver = ogr.GetDriverByName('ESRI Shapefile')

    # get layer of in_shp
    if isinstance(in_shp, str):
        ds = ogr.Open(in_shp)
    else:
        ds = in_shp

    in_layer = ds.GetLayer()
    srs = in_layer.GetSpatialRef()

    # project clip_shp
    if save_cache:
        proj_shp = rep_file('cache', os.path.splitext(
            os.path.basename(clip_shp))[0] + '_proj.shp')
    else:
        proj_shp = '/vsimem/_proj.shp'
    shp_projection(clip_shp, proj_shp, out_srs=srs)
    clip_ds = ogr.Open(proj_shp)
    clip_layer = clip_ds.GetLayer()

    # export out_shp
    if out_shp is None:
        if save_cache:
            out_shp = rep_file('cache', os.path.splitext(
                os.path.basename(clip_shp))[0] + '_out.shp')
        else:
            out_shp = '/vsimem/_out.shp'

    out_ds = driver.CreateDataSource(out_shp)
    out_layer = out_ds.CreateLayer(out_shp, srs=srs)

    in_layer.Clip(clip_layer, out_layer)

    area = []
    logK = []
    # newField = ogr.FieldDefn('Area', ogr.OFTReal)
    # out_layer.CreateField(newField)
    c = out_layer.GetFeatureCount()
    for i in range(c):
        f = out_layer.GetFeature(i)
        area.append(f.GetGeometryRef().GetArea())
        logK.append(f.GetField(field))
        # f.SetField('Area', f.GetGeometryRef().GetArea())
        # out_layer.SetFeature(f)
    area = np.array(area)
    logK = np.array(logK)
    mean_logK = np.average(logK, weights=area)
    # mean_logK = np.log10(np.average(np.power(10, logK / 100), weights=area))
    out_layer = None
    out_ds = None
    return mean_logK
