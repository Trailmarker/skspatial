__author__ = 'rosskush'

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from sklearn.neighbors import KNeighborsRegressor
from sklearn.model_selection import train_test_split
import matplotlib.pyplot as plt
from scipy import interpolate


flopy_install = True
pykrige_install = True


try:
    import flopy
except:
    flopy_install = False

try:
    from pykrige.ok import OrdinaryKriging
except:
    pykrige_install = False

class interp2d():
    def __init__(self,gdf,attribute,res=None, ulc=(np.nan,np.nan), lrc=(np.nan,np.nan)):
        """

        :param gdf: geopandas GeoDataFrame object, with geometry attribute
        :param attribute: column name in GeoDataFrame object used for spatial interpolation
        :param res: delx and dely representing pixle resolution
        :param ulc: upper left corner (x,y)
        :param lrc: lower right corner (x,y)
        """

        self.gdf = gdf
        self.attribute = attribute
        self.x = gdf.geometry.x.values
        self.y = gdf.geometry.y.values
        self.z = gdf[attribute].values
        self.crs = gdf.crs

        if np.isfinite(ulc[0]) and np.isfinite(lrc[0]):
            self.xmax = lrc[0]
            self.xmin = ulc[0]
            self.ymax = ulc[1]
            self.ymin = lrc[1]
        else:
            self.xmax = gdf.geometry.x.max()
            self.xmin = gdf.geometry.x.min()
            self.ymax = gdf.geometry.y.max()
            self.ymin = gdf.geometry.y.min()
        self.extent = (self.xmin, self.xmax, self.ymin, self.ymax)
        if np.isfinite(res):
            self.res = res
        else:
            # if res not passed, then res will be the distance between xmin and xmax / 1000
            self.res = (self.xmax - self.xmin) / 1000

        self.ncol = int(np.ceil((self.xmax - self.xmin) / self.res)) # delx
        self.nrow = int(np.ceil((self.ymax - self.ymin) / self.res))# dely
    # def points_to_grid(x, y, z, delx, dely):
    def points_to_grid(self):
        """

        :return: array of size nrow, ncol

        http://chris35wills.github.io/gridding_data/
        """
        hrange = ((self.ymin,self.ymax),(self.xmin,self.xmax)) # any points outside of this will be condisdered outliers and not used

        zi, yi, xi = np.histogram2d(self.y, self.x, bins=(int(self.nrow), int(self.ncol)), weights=self.z, normed=False,range=hrange)
        counts, _, _ = np.histogram2d(self.y, self.x, bins=(int(self.nrow), int(self.ncol)),range=hrange)
        np.seterr(divide='ignore',invalid='ignore') # we're dividing by zero but it's no big deal
        zi = np.divide(zi,counts)
        np.seterr(divide=None,invalid=None) # we'll set it back now
        zi = np.ma.masked_invalid(zi)
        array = np.flipud(np.array(zi))
    
        return array

    def knn_2D(self, k=15, weights='uniform', algorithm='brute', p=2, maxrows = 1000):

        if len(self.gdf) > maxrows:
            raise ValueError('GeoDataFrame should not be larger than 1000 rows, knn is a slow algorithim and can be too much for your computer, Change maxrows at own risk')  # shorthand for 'raise ValueError()'

        array = self.points_to_grid()
        X = []
        # nrow, ncol = array.shape
        frow, fcol = np.where(np.isfinite(array)) # find areas where finite values exist
        for i in range(len(frow)):
            X.append([frow[i], fcol[i]])
        y = array[frow, fcol]

        train_X, train_y = X, y

        knn = KNeighborsRegressor(n_neighbors=k, weights=weights, algorithm=algorithm, p=2)
        knn.fit(train_X, train_y)

        X_pred = []
        for r in range(int(self.nrow)):
            for c in range(int(self.ncol)):
                X_pred.append([r, c])
        y_pred = knn.predict(X_pred)
        karray = np.zeros((self.nrow, self.ncol))
        i = 0
        for r in range(int(self.nrow)):
            for c in range(int(self.ncol)):
                karray[r, c] = y_pred[i]
                i += 1
        return karray

    def interpolate_2D(self, method='linear',fill_value=np.nan):
        # use linear or cubic
        array = self.points_to_grid()
        x = np.arange(0, array.shape[1])
        y = np.arange(0, array.shape[0])
        # mask invalid values
        array = np.ma.masked_invalid(array)
        xx, yy = np.meshgrid(x, y)
        # get only the valid values
        x1 = xx[~array.mask]
        y1 = yy[~array.mask]
        newarr = array[~array.mask]
        GD1 = interpolate.griddata((x1, y1), newarr.ravel(), (xx, yy), method=method,fill_value=fill_value)

        return GD1

    def OrdinaryKriging_2D(self, n_closest_points=None,variogram_model='linear', verbose=False, coordinates_type='geographic'):
        # Credit from 'https://github.com/bsmurphy/PyKrige'

        if not pykrige_install:
            raise ValueError('Pykrige is not installed, try pip install pykrige')

        OK = OrdinaryKriging(self.x,self.y,self.z, variogram_model=variogram_model, verbose=verbose,
                     enable_plotting=False, coordinates_type=coordinates_type)

        x,y = np.arange(0,self.ncol), np.arange(0,self.nrow)

        krige_array, ss = OK.execute('grid', x, y,n_closest_points=n_closest_points)

        return krige_array

    def Spline_2D(self):
        array = self.points_to_grid()

        x,y = np.arange(0,self.ncol), np.arange(0,self.nrow)
        frow, fcol = np.where(np.isfinite(array))
        X = []
        for i in range(len(frow)):
            X.append([frow[i], fcol[i]])
        z = array[frow, fcol]

        sarray = interpolate.RectBivariateSpline(frow,fcol,z)
        print(sarray.shape)
        return sarray

    def RBF_2D(self):
        array = self.points_to_grid()
        print(array.shape)

        x,y = np.arange(0,self.ncol), np.arange(0,self.nrow)
        frow, fcol = np.where(np.isfinite(array))
        X = []
        for i in range(len(frow)):
            X.append([frow[i], fcol[i]])
        z = array[frow, fcol]

        rbfi = interpolate.Rbf(frow,fcol,z,kind='cubic')
        gridx, gridy = np.arange(0,self.ncol), np.arange(0, self.nrow)
        print(gridx)
        sarray = rbfi(gridx,gridy)


        print(sarray.shape)
        return sarray


    def write_raster(self,array,path):
        if '.' not in path[-4:]:
            path += '.tif'

        # transform = from_origin(gamx.min(), gamy.max(), res, res)
        transform = from_origin(self.xmin, self.ymax, self.res, self.res)


        new_dataset = rasterio.open(path, 'w', driver='GTiff',
                                    height=array.shape[0], width=array.shape[1], count=1, dtype=array.dtype,
                                    crs=self.gdf.crs, transform=transform, nodata=np.nan)
        new_dataset.write(array, 1)
        new_dataset.close()

    def write_contours(self,array,path,base=0,interval=100, levels = None):
        
        if levels is None:
            levels = np.arange(base,np.nanmax(array),interval)

        # matplotlib contour objects are shifted half a cell to the left and up
        cextent = np.array(self.extent)
        cextent[0] = cextent[0] + self.res/2.7007
        cextent[1] = cextent[1] + self.res/2.7007
        cextent[2] = cextent[2] - self.res/3.42923
        cextent[3] = cextent[3] - self.res/3.42923


        cs = plt.contour(np.flipud(array),extent=cextent,levels=levels)
        delr = np.ones(int(self.ncol)) * self.res
        delc = np.ones(int(self.nrow)) * self.res
        # print(self.crs)
        sr = flopy.utils.SpatialReference(delr,delc,3,self.xmin,self.ymax)#epsg=self.epsg)
        sr.export_contours(path,cs,epsg=self.crs) #crs_wkt=
        plt.close('all')

    def plot_image(self,array,title=''):
        fig, axes = plt.subplots(figsize=(10,8))
        plt.imshow(array, cmap='jet',extent=self.extent)
        plt.colorbar()
        plt.title(title)
        fig.tight_layout()
        return axes

if __name__ == '__main__':
    # for testing only
    import os

    gdf = gpd.read_file(os.path.join('..','examples','data','inputs_pts.shp'))
    print(len(gdf))
    res = 5280/8 # 8th of a mile grid size
    ml = interp2d(gdf,'z',res=res)

    # array = ml.OrdinaryKriging_2D(variogram_model='linear', verbose=False, coordinates_type='geographic')
    array = ml.RBF_2D()
    # array_near = ml.interpolate_2D(method='nearest')
    # array = ml.interpolate_2D(method='linear')
    # array[np.isnan(array)] = array_near[np.isnan(array)]
    #
    plt.imshow(array, cmap='jet')
    plt.colorbar()
    #
    plt.show()



