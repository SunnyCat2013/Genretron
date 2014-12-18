"""
The GTZAN dataset.
"""
__authors__ = "Carmine Paolino"
__copyright__ = "Copyright 2014, Vrije Universiteit Amsterdam"
__credits__ = ["Carmine Paolino"]
__license__ = "3-clause BSD"
__email__ = "carmine@paolino.me"

import os
import warnings
import gc
try:
    import tables
except ImportError:
    warnings.warn("Couldn't import tables, so far GTZAN is "
                  "only supported with PyTables")
import numpy
from theano import config
from collections import OrderedDict
from scikits.audiolab import Sndfile
from scikits.audiolab import available_file_formats
from pylearn2.datasets import dense_design_matrix
from pylearn2.utils import string_utils
from pylearn2.utils.rng import make_np_rng
from spectrogram import Spectrogram
from kfold import KFold


class GTZAN(dense_design_matrix.DenseDesignMatrixPyTables):
    """
    The GTZAN dataset

    Parameters
    ----------

    feature: str
        Which feature to use (either "raw" or "spectrogram")

    center: WRITEME
    scale: WRITEME
    start: WRITEME
    stop: WRITEME
    axes: WRITEME
    preprocessor: WRITEME


    """

    features = {'spectrogram': 0, 'mfcc': 1}
    sets = {'train': 0, 'test': 1, 'valid': 2}
    data_path = "${PYLEARN2_DATA_PATH}/GTZAN/"
    number_of_tracks = 1000
    seconds = 29
    sample_rate = 22050
    window_size = 2048
    step_size = window_size / 2
    fft_resolution = 1024
    wins_per_track = len(Spectrogram.wins(window_size, seconds * sample_rate, step_size))
    bins_per_track = Spectrogram.bins(fft_resolution)
    genres = ['blues', 'classical', 'country', 'disco', 'hiphop',
              'jazz', 'metal', 'pop', 'reggae', 'rock']
    image_size = wins_per_track * bins_per_track

    def __init__(self, which_set, feature="spectrogram", path=None,
                 center=False, scale=False, start=None, stop=None,
                 axes=('b', 0, 1, 'c'), preprocessor=None):

        assert which_set in self.sets.keys()
        assert feature in self.features.keys()

        self.__dict__.update(locals())
        del self.self

        if path is None:
            path = self.data_path
            mode = 'r'
        else:
            mode = 'r+'
            warnings.warn("Because path is not same as PYLEARN2_DATA_PATH "
                          "be aware that data might have been "
                          "modified or pre-processed.")

        if mode == 'r' and (scale or
                            center or
                            (start is not None) or
                            (stop is not None)):
            raise ValueError("Only for speed there is a copy of hdf5 file in "
                             "PYLEARN2_DATA_PATH but it meant to be only "
                             "readable. If you wish to modify the data, you "
                             "should pass a local copy to the path argument.")

        path = string_utils.preprocess(path)
        file_n = os.path.join(path, "%s_%s.h5" % (feature, which_set))
        if not os.path.isfile(file_n):
            self.filters = tables.Filters(complib='blosc:lz4', complevel=5)
            self.make_data(which_set, path, feature)

        self.h5file = tables.open_file(file_n, mode=mode)
        data = self.h5file.root.Data

        if start is not None or stop is not None:
            self.h5file, data = self.resize(self.h5file, start, stop)

        # import ipdb; ipdb.set_trace()
        # TODO: center and scale
        # if center and scale:
        #     data.X[:] -= 127.5
        #     data.X[:] /= 127.5
        # elif center:
        #     data.X[:] -= 127.5
        # elif scale:
        #     data.X[:] /= 255.

        view_converter = dense_design_matrix.DefaultViewConverter((self.bins_per_track, self.wins_per_track, 1), axes)

        # super(GTZAN, self).__init__(topo_view=data.X, y=data.y,
        #                             axes=axes)
        super(GTZAN, self).__init__(X=data.X, y=data.y,  # y_labels=10,
                                    view_converter=view_converter)

        if preprocessor:
            if which_set in ['train']:
                can_fit = True
            preprocessor.apply(self, can_fit)

        self.h5file.flush()

    def get_test_set(self):
        """
        .. todo::

            WRITEME
        """
        return GTZAN(which_set='test', feature=self.feature,
                     path=self.path, center=self.center,
                     scale=self.scale, start=self.start,
                     stop=self.stop, axes=self.axes,
                     preprocessor=self.preprocessor)

    def make_data(self, which_set, path, feature,
                  shuffle=True, n_folds=4):
        """
        .. todo::

            WRITEME
        """
        sizes = {'train': 500, 'test': 250, 'valid': 250}
        h_file_n = os.path.join(path, "%s_%s.h5" % (feature, which_set))
        h5file, node = self.init_hdf5(h_file_n,
                                      ([sizes[which_set], self.image_size],
                                       [sizes[which_set], len(self.genres)]))

        rng = make_np_rng(None, 322, which_method="shuffle")

        def list_audio_files_and_genres(audio_folder, extensions):
            files = OrderedDict()
            for root, dirnames, filenames in os.walk(audio_folder):
                for f in filenames:
                    for x in extensions:
                        if f.endswith(x):
                            filename = os.path.join(root, f)
                            genre = os.path.basename(root)
                            files[filename] = genre
            return files

        def load_raw_data(path, indexes):
            """Loads data from the genres folder"""
            window_type = 'square'

            extensions = available_file_formats()
            audiofiles = list_audio_files_and_genres(path, extensions).items()
            data_x = numpy.zeros((len(indexes), self.bins_per_track * self.wins_per_track), dtype=config.floatX)
            data_y = numpy.zeros((len(indexes), len(self.genres)), dtype=numpy.int8)

            for data_i, index in enumerate(indexes):
                filename = audiofiles[index][0]
                genre = audiofiles[index][1]
                f = Sndfile(filename, mode='r')
                print("Reading %s" % filename)
                raw_audio = f.read_frames(self.seconds * self.sample_rate)
                spectrogram = Spectrogram.from_waveform(raw_audio, self.window_size,
                                                        self.step_size, window_type,
                                                        self.fft_resolution).spectrogram
                data_x[data_i] = spectrogram.T.reshape(spectrogram.shape[0] * spectrogram.shape[1])
                data_y[data_i][self.genres.index(genre)] = 1

            return data_x, data_y

        tracks = numpy.arange(self.number_of_tracks)
        if shuffle:
            rng.shuffle(tracks)
        kf = KFold(tracks, n_folds=n_folds)
        run = kf.runs[0]
        data_x, data_y = load_raw_data(path, run[which_set])

        assert data_x.shape[0] == sizes[which_set]
        assert data_x.shape[1] == self.wins_per_track * self.bins_per_track
        assert data_y.shape[0] == sizes[which_set]
        assert data_y.shape[1] == len(self.genres)

        GTZAN.fill_hdf5(h5file, data_x, data_y, node)
        h5file.close()


class GTZAN_On_Memory(dense_design_matrix.DenseDesignMatrix):
    """
    The GTZAN dataset

    Parameters
    ----------

    feature: str
        Which feature to use (either "raw" or "spectrogram")

    center: WRITEME
    scale: WRITEME
    start: WRITEME
    stop: WRITEME
    axes: WRITEME
    preprocessor: WRITEME
    seconds: WRITEME
    window_size: WRITEME
    fft_resolution: WRITEME


    """

    features = ['spectrogram', 'mfcc', 'inv_spectrogram', 'inv_mfcc']
    sets = ['train', 'test', 'valid']
    data_path = "${PYLEARN2_DATA_PATH}/GTZAN/"
    number_of_tracks = 1000
    sample_rate = 22050
    genres = ['blues', 'classical', 'country', 'disco', 'hiphop',
              'jazz', 'metal', 'pop', 'reggae', 'rock']

    def __init__(self, which_set, feature="spectrogram", path=None,
                 center=False, scale=False, start=None, stop=None,
                 axes=('b', 0, 1, 'c'), preprocessor=None,
                 seconds=29.0, window_size=1024, fft_resolution=1024,
                 seed=1234, transpose=True):

        assert which_set in self.sets
        assert feature in self.features

        self.__dict__.update(locals())
        del self.self

        self.step_size = self.window_size / 2
        self.wins_per_track = len(Spectrogram.wins(self.window_size, self.seconds * self.sample_rate, self.step_size))
        self.bins_per_track = Spectrogram.bins(self.fft_resolution)
        self.image_size = self.wins_per_track * self.bins_per_track

        if path is None:
            path = self.data_path
            mode = 'r'
        else:
            mode = 'r+'
            warnings.warn("Because path is not same as PYLEARN2_DATA_PATH "
                          "be aware that data might have been "
                          "modified or pre-processed.")

        if mode == 'r' and (scale or
                            center or
                            (start is not None) or
                            (stop is not None)):
            raise ValueError("Only for speed there is a copy of hdf5 file in "
                             "PYLEARN2_DATA_PATH but it meant to be only "
                             "readable. If you wish to modify the data, you "
                             "should pass a local copy to the path argument.")

        path = string_utils.preprocess(path)
        data_x, data_y = self.make_data(which_set, path, feature, seed, transpose)

        # import ipdb; ipdb.set_trace()
        # TODO: center and scale
        # if center and scale:
        #     data.X[:] -= 127.5
        #     data.X[:] /= 127.5
        # elif center:
        #     data.X[:] -= 127.5
        # elif scale:
        #     data.X[:] /= 255.

        view_converter = dense_design_matrix.DefaultViewConverter((self.bins_per_track, self.wins_per_track, 1), axes)

        super(GTZAN_On_Memory, self).__init__(X=data_x, y=data_y,
                                              view_converter=view_converter)

        if preprocessor:
            if which_set in ['train']:
                can_fit = True
            preprocessor.apply(self, can_fit)

        del data_x, data_y
        gc.collect()

    def get_test_set(self):
        """
        .. todo::

            WRITEME
        """
        return GTZAN_On_Memory(which_set='test', feature=self.feature,
                               path=self.path, center=self.center,
                               scale=self.scale, start=self.start,
                               stop=self.stop, axes=self.axes,
                               preprocessor=self.preprocessor,
                               )

    def make_data(self, which_set, path, feature,
                  seed, transpose,
                  shuffle=True, n_folds=4):
        """
        .. todo::

            WRITEME
        """

        rng = make_np_rng(None, seed, which_method="shuffle")

        def list_audio_files_and_genres(audio_folder, extensions):
            files = OrderedDict()
            for root, dirnames, filenames in os.walk(audio_folder):
                for f in filenames:
                    for x in extensions:
                        if f.endswith(x):
                            filename = os.path.join(root, f)
                            genre = os.path.basename(root)
                            files[filename] = genre
            return files

        def load_raw_data(path, indexes, transpose):
            """Loads data from the genres folder"""
            window_type = 'square'

            extensions = available_file_formats()
            audiofiles = list_audio_files_and_genres(path, extensions).items()
            data_x = numpy.zeros((len(indexes), self.bins_per_track * self.wins_per_track), dtype=config.floatX)
            data_y = numpy.zeros((len(indexes), len(self.genres)), dtype=numpy.int8)

            for data_i, index in enumerate(indexes):
                filename = audiofiles[index][0]
                genre = audiofiles[index][1]
                f = Sndfile(filename, mode='r')
                print("Reading %s" % filename)
                raw_audio = f.read_frames(self.seconds * self.sample_rate)
                spectrogram = Spectrogram.from_waveform(raw_audio,
                                                        self.window_size,
                                                        self.step_size,
                                                        window_type,
                                                        self.fft_resolution).spectrogram
                if transpose:
                    spectrogram = spectrogram.T
                data_x[data_i] = spectrogram.reshape(
                    spectrogram.shape[0] * spectrogram.shape[1])
                data_y[data_i][self.genres.index(genre)] = 1

            return data_x, data_y

        tracks = numpy.arange(self.number_of_tracks)
        if shuffle:
            rng.shuffle(tracks)
        kf = KFold(tracks, n_folds=n_folds)
        run = kf.runs[0]
        data_x, data_y = load_raw_data(path, run[which_set], transpose)

        assert data_x.shape[0] == len(run[which_set])
        assert data_x.shape[1] == self.wins_per_track * self.bins_per_track
        assert data_y.shape[0] == len(run[which_set])
        assert data_y.shape[1] == len(self.genres)

        return data_x, data_y
