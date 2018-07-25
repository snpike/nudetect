'''
Module with functions for analysis of gamma flood data.
PH: Pulse height
STIM: Mask value. If 1, event is from voltage pulse, not photon. (Usually applied to pixel (10, 10))
UP: micro pluse -- also a mask (in noise)
'''

# Packages for making life easier
import os.path

# Data analysis packages
import numpy as np
from astropy.io import fits
from astropy.modeling import models, fitting

# Bokeh for interactive plots (v. 0.13.0 at time of writing)
import bokeh.io
import bokeh.plotting
import bokeh.models as bm

# Matplotlib for static plots
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.gridspec import GridSpec
import seaborn as sns

class Line:
    '''
    A class for spectral lines. The infomation in each instance will help
    supply parameters for fitting peaks.

    Attributes:
        source: str
            The name of the radioactive source producing the line. 
            E.g., 'Am241'
        energy: float
            The energy of the line in keV.
        chan_low: int
            When searching the channel spectrum for peaks, channels below
            'chan_low' will be ignored.
        chan_high: int
            When searching the channel spectrum for peaks, channels above
            'chan_high' will be ignored.
    '''
    def __init__(self, source, energy, chan_low, chan_high):
        self.source = source
        self.energy = energy
        self.chan_low = chan_low
        self.chan_high = chan_high

# Defining 'Line' instances for Am241 and Co57. 
am = Line('Am241', 59.54, chan_low=3000, chan_high=6000)
# Co57's 'chan_low' and 'chan_high' attributes have not been tested.
co = Line('Co57', 122.06, chan_low=5000, chan_high=8000)


def construct_path(filepath,  description='', etc='', ext='', save_dir='',
    sep_by_detector=False, detector=''):
    '''
    Constructs a path for saving data and figures based on user input. The 
    main use of this function is for other functions in this package to use 
    it as the default path constructor if the user doesn't supply their own 
    function.

    Note to developers: This function is designed to throw a lot of 
    exceptions and be strict about formatting early on to avoid 
    complications later. Call it early in scripts to avoid losing the 
    results of a long computation to a mistyped directory.

    Arguments:
        filepath: str
            This string will form the basis for the file name in the path 
            returned by this function. If a path is supplied here, the 
            file name sans extension will be trimmed out and used.

    Keyword Arguments:
        ext: str
            The file name extension.
        description: str
            A short description of what the file contains. This will be 
            prepended to the file name.
            (default: '')
        etc: str 
            Other important information, e.g., pixel coordinates. This will 
            be appended to the file name.
            (default: '')
        save_dir: str
            The directory to which the file will be saved. If left
            unspecified, the file will be saved to the current directory.
            (default: '')
        sep_by_detector: bool
            If True, constructs the file path such that the file is saved in 
            a subdirectory of 'save_dir' named according to the string 
            passed for 'detector'. Setting this to 'True' makes 'detector' a 
            required kwarg.
            (default: False)
        detector: str
            The detector ID.

    Return:
        save_path: str
            A Unix/Linux/MacOS style path that can be used to save data
            and plots in an organized way.
    '''
    ### Handling exceptions and potential errors

    # If 'ext' does not start with a '.', fix it.
    if ext and ext[0] != '.':
        ext = f'.{ext}'

    # Check that the save directory exists
    if save_dir and sep_by_detector:
        if not os.path.exists(f'{save_dir}/{detector}'):
            raise ValueError(
                f'The directory \'{save_dir}/{detector}\' does not exist.'
            )
    elif save_dir:
        if not os.path.exists(save_dir):
            raise ValueError(f'The directory \'{save_dir}\' does not exist.')

    ### Constructing the path name

    # Construct the file name from the file name in 'filepath'.
    filename = os.path.basename(filepath)
    save_path = os.path.splitext(filename)[0].replace('.', '_')
    
    # Prepend the description if specified
    if description:
        save_path = f'{description}_{save_path}'

    # Append extra info to the file name if specified
    if etc:
        save_path += f'_{etc}'


    # Append the file extension
    save_path += ext

    # Prepend the detector directory if desired
    if sep_by_detector:
        if not detector:
            raise Exception('''
                Since 'sep_by_detector' is True, a value must be supplied
                for the kwarg 'detector'.
            ''')

        save_path = f'{detector}/{save_path}'

    # Prepend the save directory if specified
    if save_dir:
        save_path = f'{save_dir}/{save_path}'


    return save_path


def count_map(filepath, save=True, path_constructor=construct_path,
    etc='', ext='.txt', save_dir='', sep_by_detector=False, detector=''):
    '''
    Generates event count data for each pixel for raw gamma flood data.

    Arguments:
        filepath: str
            The filepath to the gamma flood data.

    Keyword Arguments:
        save: bool 
            If True, saves count_map as an ascii file.
            (default: True)
        path_constructor: function
            A function that takes the same parameters as the function
            'gamma.construct_path' that returns a string representing a 
            path to which the file will be saved.
            (default: gamma.construct_path)
        etc: str 
            Other important information. Will be appended to the file name.
            (default: '')
        save_dir: str
            The directory to which the count_map file will be saved. If left
            unspecified, the file will be saved to the current directory.
            (default: '')
        sep_by_detector: bool
            If True, constructs the file path such that the file is saved in 
            a subdirectory of 'save_dir' named according to the string 
            passed for 'detector'. Setting this to 'True' makes 'detector' a 
            required kwarg.
            (default: False)
        detector: str
            The detector ID
        ext: str
            The file name extension for the count_map file. 
            (default: '.txt')

    Return:
        count_map: 2D numpy.ndarray
            A 32 x 32 array of floats. Each entry represents the number of
            counts read by the detector pixel at the corresponding index.
    '''
    # Generating the save path, if needed.
    if save:
        save_path = path_constructor(filepath, ext=ext
            save_dir=save_dir, sep_by_detector=sep_by_detector, 
            detector=detector, etc=etc)

    # Get data from gamma flood FITS file
    with fits.open(filepath) as file:
        data = file[1].data

    # The masks ('mask', 'PHmask', 'STIMmask', and 'TOTmask') below show 
    # 'True' or '1' for valid/desired data points, and 'False' or '0' 
    # otherwise. Note that this is the reverse of numpy's convention for 
    # masking arrays.

    # 'START' and 'END' denote the indices between which 'data['TEMP']'
    # takes on a resonable value. START is the first index with a 
    # temperature greater than -20 C, and END is the last such index.
    mask = data['TEMP'] > -20
    START = np.argmax(mask)
    END = len(mask) - np.argmax(mask[::-1])

    # Masking out non-positive pulse heights
    PHmask = 0 < np.array(data['PH'][START:END])
    # Masking out artificially stimulated events
    STIMmask = np.array(data['STIM'][START:END]) == 0
    # Combining the above masks
    TOTmask = np.multiply(PHmask, STIMmask)

    # Generate the count_map from event data
    count_map = np.zeros((32, 32))

    for i in range(32):
        RAWXmask = np.array(data['RAWX'][START:END]) == i
        for j in range(32):
            RAWYmask = np.array(data['RAWY'][START:END]) == j
            count_map[i, j] = np.sum(np.multiply(
                TOTmask, np.multiply(RAWXmask, RAWYmask)))

    # Saves the 'count_map' array as an ascii file.
    if save:
        np.savetxt(save_path, count_map)

    return count_map


def bokeh_pixel_map(values, value_label, title='Pixel Map', 
    plot_width=650, plot_height=600, low=None, high=None, low_color='grey', 
    high_color='red', palette='Viridis256', save=True, 
    path_constructor=construct_path, filepath='', etc='', save_dir='', 
    sep_by_detector=False, detector=''):
    '''
    Plots a heat map of 'values' across the detector pixels.

    Arguments:
        values: 2D array
            A 32 x 32 array of numbers.
        value_label: str
            A short label denoting what data is supplied in 'values'.
            In the hover tooltip, the pixel's value will be labelled with 
            this string. E.g., if value_label = 'Counts', the tooltip might
            read 'Counts: 12744'. The color bar title is also set to this 
            value. Also, value_label.lower() is prepended to the file name
            if saving the plot.

    Kwargs for Bokeh plot formatting:
        title: str
            The title displayed on the plot.
            (default: 'Pixel Map')
        plot_width: int
            The width of the plot in pixels
            (default: 650)
        plot_height: int
            The height of the plot in pixels
            (default: 600)
        low: int or float
            The value below which elements of values are mapped to the
            lowest color.
            (default: lowest non-zero value in values)
        high: int or float
            The value above which elements of values are mapped to the
            highest color.
            (default: largest non-zero value in values)
        low_color: str or 3-tuple of ints or 4-tuple(int, int, int, float)
            Color to be used if data is lower than low value. If None,
            values lower than low are mapped to the first color in the
            palette. If str, must be either a hex string starting with '#' 
            or a named SVG color. If a tuple, can be an RGB 3-tuple or an
            RGBA 4-tuple. For details,
            https://bokeh.pydata.org/en/latest/docs/reference/core/
            properties.html#bokeh.core.properties.Color
            (default: 'grey')
        high_color: str or 3-tuple of ints or 4-tuple(int, int, int, float)
            Color to be used if data is higher than 'high' value. If None, 
            values higher than 'high' are mapped to the last color in the 
            palette. See 'low_color' for help formatting this parameter.
            (default: 'red')
        palette: str or sequence
            A sequence of colors to use as the target palette for mapping.
            This property can also be set as a String, to the name of any 
            of the palettes shown in bokeh.palettes. For example, you could
            also set the palette to 'Inferno256', 'Magma256', or 'Plamsa256'.
            (default: 'Viridis256')

    Kwargs for saving the plot to a file:
        save: bool
            If True, saves the Bokeh plot as an HTML file.
        filepath: str
            This string will form the basis for the file name in the path 
            returned by this function. If a path is supplied here, the 
            file name sans extension will be trimmed out and used.
        path_constructor: function
            A function that takes the same parameters as the function
            'gamma.construct_path' that returns a string representing a 
            path to which the file will be saved.
            (default: gamma.construct_path)
        etc: str 
            Other important information. Will be appended to the file name.
            (default: '')
        save_dir: str
            The directory to which the count_map file will be saved. If left
            unspecified, the file will be saved to the current directory.
            (default: '')
        sep_by_detector: bool
            If True, constructs the file path such that the file is saved in 
            a subdirectory of 'save_dir' named according to the string 
            passed for 'detector'. Setting this to 'True' makes 'detector' a 
            required kwarg.
            (default: False)
        detector: str
            The detector ID

    Return:
        A bokeh.plotting.Figure object with a heat map of 'values'
        plotted. 
    '''
    # Generate a save path, if needed.
    if save:
        description = (value_label.lower() + '_map').replace(' ', '_')
        save_path = path_constructor(filepath, ext='.html', 
            description=description, save_dir=save_dir, etc=etc, 
            sep_by_detector=sep_by_detector, detector=detector)

    # Put data in a ColumnDataSource object such that data will display
    # correctly upon hovering over a pixel.
    source = bm.ColumnDataSource(data={
        'x': [0.5],
        'y': [0.5],
        'values': [values]
    })

    # Format of the tooltip when hovering over a pixel.
    tooltips = [
        ('(x, y)', '($x{g}, $y{g})'),
        (value_label, '@values')
    ]

    # Generates the figure canvas 'p'
    p = bokeh.plotting.figure(plot_width=plot_width, plot_height=plot_height,
        x_range=(0.5, 32.5), y_range=(0.5, 32.5),
        tools='pan,wheel_zoom,box_zoom,save,reset,hover',
        tooltips=tooltips, toolbar_location='above', title=title)

    # Set heatmap axes to have tick intervals scale by a factor of 2.
    # This causes the 32nd pixel to have its own tick. 
    axis_ticker = bm.AdaptiveTicker(max_interval=None, min_interval=1, 
        num_minor_ticks=0, mantissas=[2], base=2)
    p.xaxis.ticker = axis_ticker
    p.yaxis.ticker = axis_ticker

    # If not specified, assign values to 'high' and 'low' based on data.
    if (not low) or (not high):
        flat_counts = values.flatten()
        flat_counts = np.ma.masked_values(flat_counts, 0)
    if not low:
        low = np.amin(flat_counts)
    if not high:
        high = np.amax(flat_counts)

    # Formatting the color bar
    color_mapper = bm.LinearColorMapper(palette=palette, 
    low=low, high=high, low_color=low_color, high_color=high_color)

    cb_ticker = bm.AdaptiveTicker()

    color_bar = bm.ColorBar(location=(0, 0), ticker=cb_ticker,
        label_standoff=8, color_mapper=color_mapper,
        title=value_label, title_standoff=12)

    p.add_layout(color_bar, 'right')

    # Generates the heatmap itself
    p.image(source=source, image='values', x='x', y='y', dw=32, dh=32,
        color_mapper=color_mapper)

    if save:
        bokeh.io.save(p, filename=save_path)

    return p


def mpl_pixel_map(values, value_label, title='', save=True, filepath='', 
    path_constructor=construct_path, etc='', ext='.eps', save_dir='', 
    sep_by_detector=False, detector=''):
    '''
    Construct a heatmap of counts across the detector using matplotlib.

    Arguments:
        values: 2D array
            A 32 x 32 array of numbers.
        value_label: str
            A short label denoting what data is supplied in 'values'.
            In the hover tooltip, the pixel's value will be labelled with 
            this string. E.g., if value_label = 'Counts', the tooltip might
            read 'Counts: 12744'. The color bar title is also set to this 
            value. Also, value_label.lower() is prepended to the file name
            if saving the plot.

    Keyword Arguments:
        title: str
            The title displayed on the plot.
            (default: 'Pixel Map')
        save: bool
            If True, saves the Bokeh plot as an HTML file.
        filepath: str
            This string will form the basis for the file name in the path 
            returned by this function. If a path is supplied here, the 
            file name sans extension will be trimmed out and used.
        path_constructor: function
            A function that takes the same parameters as the function
            'gamma.construct_path' that returns a string representing a 
            path to which the file will be saved.
            (default: gamma.construct_path)
        etc: str 
            Other important information. Will be appended to the file name.
            (default: '')
        save_dir: str
            The directory to which the count_map file will be saved. If left
            unspecified, the file will be saved to the current directory.
            (default: '')
        sep_by_detector: bool
            If True, constructs the file path such that the file is saved in 
            a subdirectory of 'save_dir' named according to the string 
            passed for 'detector'. Setting this to 'True' makes 'detector' a 
            required kwarg.
            (default: False)
        detector: str
            The detector ID

    '''
    # Generate a save path, if needed.
    if save:
        description = (value_label.lower() + '_map').replace(' ', '_')
        save_path = path_constructor(filepath, ext=ext, 
            description=description, save_dir=save_dir, etc=etc, 
            sep_by_detector=sep_by_detector, detector=detector)

    plt.figure()
    masked = np.ma.masked_values(values, 0.0)
    current_cmap = mpl.cm.get_cmap()
    current_cmap.set_bad(color='gray')
    plt.imshow(masked)
    c = plt.colorbar()
    c.set_label(value_label)
    plt.title(title)
    plt.tight_layout()

    if save:
        plt.savefig(save_path)

    plt.show()
    plt.close()


def bokeh_hist(count_map, bins=100, plot_width=600, plot_height=500,
    title='Count Histogram', save=True, filepath='', save_dir='', etc='',
    path_constructor=construct_path, sep_by_detector=False, detector=''):
    '''
    Plots a count histogram with respect to the pixels.

    Arguments:
        count_map: 2D array
            A 32 x 32 array of numbers. Each entry represents the number of
            counts read by the detector pixel at the corresponding index.

    Keyword Arguments:
        bins : int or sequence of scalars or str, optional
            If `bins` is an int, it defines the number of equal-width
            bins in the given range (10, by default). If `bins` is a
            sequence, it defines the bin edges, including the rightmost
            edge, allowing for non-uniform bin widths.
            For information about str values of 'bins', see the numpy
            documentation of the parameter with 'help(np.histogram)'.
        plot_width: int
            The width of the plot in pixels
            (default: 600)
        plot_height: int
            The height of the plot in pixels
            (default: 500)
        title: str
            The title displayed on the plot.
            (default: 'Count Histogram')
    '''
    # Generating a save path, if needed.
    if save:
        save_path = path_constructor(filepath, ext='.html', etc=etc, save_dir=save_dir, description='count_hist', sep_by_detector=sep_by_detector, detector=detector)

    # Binning the data
    counts = count_map.flatten()
    hist, edges = np.histogram(count_map, bins=bins)

    # Generating the Figure object 'p'
    p = bokeh.plotting.figure(plot_width=plot_width, plot_height=plot_height,
        title=title, x_axis_label='Counts', y_axis_label='Number of Pixels')

    # Plotting rectangular glyphs for bins.
    p.quad(left=edges[:-1], right=edges[1:], top=hist, bottom=0)

    if save:
        bokeh.io.save(p, filename=save_path)

    return p


def mpl_hist(count_map, bins=100, title='Count Histogram', save=True, 
    filepath='', etc='', ext='.eps', path_constructor=construct_path, 
    save_dir='', sep_by_detector=False, detector=''):

    # Generate a save path, if needed.
    if save:
        save_path = path_constructor(filepath, ext=ext, etc=etc,
            description='count_hist', save_dir=save_dir, 
            sep_by_detector=sep_by_detector, detector=detector)

    plt.figure()
    plt.hist(np.array(count_map).flatten(), bins=bins, 
        range=(0, np.max(count_map) + 1), 
        histtype='stepfilled')
    plt.ylabel('Pixels')
    plt.xlabel('Counts')
    plt.title(title)
    plt.tight_layout()

    if save:
        plt.savefig(save_path)

    plt.show()
    plt.close()


def quick_gain(filepath, line, path_constructor=construct_path, 
    save_plot=True, plot_dir='', plot_ext='.eps', plot_sep_by_detector=True, 
    save_data=True, data_dir='', data_ext='.txt', data_sep_by_detector=False,
    etc='', detector=''):
    '''
    Generates gain correction data from the raw gamma flood event data.
    Currently, the fitting done might fail for sources other than Am241.

    Arguments:
        filepath: str
            The filepath to the gamma flood data
        line: an instance of Line
            The attributes of 'line' will provide information for fitting.

    Keyword Arguments:
        save_plot: bool
            If true, plots and energy spectrum for each pixel and saves
            the figure.
            (default: True)
        save_data: bool 
            If True, saves count_map as a .txt file.
            (default: True)
        save_dir: str
            The directory to which the count_map file will be saved. If left
            unspecified, the file will be saved to the current directory.
            (default: '')
        ext: str
            The file name extension for the count_map file. 
            (default: '.txt')
        etc: str 
            Other important information
            (default: '')

    Return:
        gain: 2D numpy.ndarray
            A 32 x 32 array of floats. Each entry represents its respective 
            pixel's gain, where channels * gain = energy
    '''

    if save_data:
        data_path = path_constructor(filepath=filepath, ext=data_ext,
            description='gain', sep_by_detector=data_sep_by_detector,
            detector=detector, etc=etc)

    if save_plot:
        plot_path = path_constructor(filepath=filepath, description='gain',
            sep_by_detector=plot_sep_by_detector, detector=detector, etc=etc)


    # Get data from gamma flood FITS file
    with fits.open(filepath) as file:
        data = file[1].data

    mask = data['TEMP'] > -20

    START = np.argmax(mask)
    END = len(mask) - np.argmax(mask[::-1])

    maxchannel = 10000
    bins = np.arange(1, maxchannel)
    gain = np.zeros((32, 32))

    # Iterating through pixels
    for x in range(32):
        RAWXmask = data.field('RAWX')[START:END] == x
        for y in range(32):
            # Getting peak height in 'channels' for all events for the 
            # current pixel.
            channel = data.field('PH')[START:END][np.nonzero(
                np.multiply(
                    RAWXmask, data.field('RAWY')[START:END] == y
                ))]

            # If there were events at this pixel, fit the strongest peak
            # in the channel spectrum with a Gaussian.
            if len(channel):
                # 'spectrum' contains counts at each channel
                spectrum, edges = np.histogram(channel, bins=bins, 
                    range=(0, maxchannel))
                # 'centroid' is the channel with the most counts in the 
                # interval between 'line.chan_low' and 'line.chan_high'.
                centroid = np.argmax(spectrum[line.chan_low:line.chan_high])\
                    + line.chan_low
                fit_channels = np.arange(centroid - 100, centroid + 200)
                g_init = models.Gaussian1D(amplitude=spectrum[centroid], 
                    mean=centroid, stddev=75)
                fit_g = fitting.LevMarLSQFitter()
                g = fit_g(g_init, fit_channels, spectrum[fit_channels])

                # If we can determine the covariance matrix (which implies
                # that the fit succeeded), then calculate this pixel's gain
                if fit_g.fit_info['param_cov'] is not None:
                    gain[y, x] = line.energy / g.mean
                    # Plot each pixel's spectrum
                    if save_plot:
                        plt.figure()
                        sigma_err = np.diag(fit_g.fit_info['param_cov'])[2]
                        fwhm_err = 2 * np.sqrt(2 * np.log(2)) * sigma_err
                        mean_err = np.diag(fit_g.fit_info['param_cov'])[1]
                        frac_err = np.sqrt(np.square(fwhm_err) 
                            + np.square(g.fwhm * mean_err / g.mean)) / g.mean
                        str_err = str(int(round(frac_err * line.energy * 1000)))
                        str_fwhm = str(int(round(
                                line.energy * 1000 * g.fwhm / g.mean, 0
                        )))
                        plt.text(
                            maxchannel * 3 / 5, spectrum[centroid] * 3 / 5, 
                            r'$\mathrm{FWHM}=$' + str_fwhm + r'$\pm$' 
                            + str_err + ' eV', fontsize=13
                        )

                        plt.hist(
                            np.multiply(channel, gain[y, x]), 
                            bins=np.multiply(bins, gain[y, x]),
                            range=(0, maxchannel * gain[y, x]), 
                            histtype='stepfilled'
                        )

                        plt.plot(
                            np.multiply(fit_channels, gain[y, x]), 
                            g(fit_channels), label='Gaussian fit'
                        )

                        plt.ylabel('Counts')
                        plt.xlabel('Energy')
                        plt.legend()
                        plt.tight_layout()
                        plt.savefig(f'{plot_path}_x{x}_y{y}{plot_ext}')
                        plt.close()

    # Interpolate gain for pixels where fit was unsuccessful. Do it twice in
    # case the first pass had insufficient data to interpolate some pixels.
    for _ in range(2):
        newgain = np.zeros((34, 34))
        # Note that newgain's indices will be shifted over one from 'gain'.
        newgain[1:33, 1:33] = gain
        # 'empty' contains indices at which the fit was unsuccessful
        empty = np.transpose(np.nonzero(gain == 0.0))
        # Iterating through pixels with failed fitting.
        for x in empty:
            # 'temp' is the 3x3 array of gain values around the pixel for 
            # which the fitting failed.
            temp = newgain[x[0]:x[0]+3, x[1]:x[1]+3]
            # If there are any nonzero values in 'temp', set the pixel's 
            # gain to their mean.
            if np.count_nonzero(temp):
                gain[x[0], x[1]] = np.sum(temp) / np.count_nonzero(temp)

    # Save gain data to an ascii file.
    if save_data:
        np.savetxt(data_path, gain)

    return gain


def get_spectrum(filepath, gain, bins=10000, energy_range=(0.01, 120), 
    path_constructor=construct_path, save=True, ext='.txt', save_dir='', 
    sep_by_detector=False, detector='', etc=''):
    '''
    Applies gain correction to get energy data, and then bins the events
    by energy to obtain a spectrum.

    Arguments:
        filepath: str
            The filepath to the gamma flood data
        gain: 2D numpy.ndarray
            A 32 x 32 array of floats. Each entry represents its respective 
            pixel's gain, where channels * gain = energy

    Keyword Arguments:
        bins: int
            Number of energy bins
        energy_range: tuple of numbers
            The bins will be made between these energies
        path_constructor: function
            A function that takes the same parameters as the function
            'gamma.construct_path' that returns a string representing a 
            path to which the file will be saved.
            (default: gamma.construct_path)
        save:
            If True, 'spectrum' will be saved as an ascii file. Parameters 
            relevant to this saving are below
        etc: str 
            Other important information to go in the filename.
            (default: '')
        save_dir: str
            The directory to which the  file will be saved. If left
            unspecified, the file will be saved to the current directory.
            (default: '')
        sep_by_detector: bool
            If True, constructs the file path such that the file is saved in 
            a subdirectory of 'save_dir' named according to the string 
            passed for 'detector'. Setting this to 'True' makes 'detector' a 
            required kwarg.
            (default: False)
        detector: str
            The detector ID. Required if sep_by_detector == True.
        ext: str
            The file name extension for the count_map file. 
            (default: '.txt')

    Return:
        spectrum: 2D numpy.ndarray
            This array represents a histogram wrt the energy of an event.
            spectrum[0] is a 1D array of counts in each bin, and spectrum[1] 
            is a 1D array of the middle enegies of each bin in keV. E.g., if 
            the ith bin counted events between 2 keV and 4 keV, then the 
            value of spectrum[1, i] is 3.
    '''
    # Generating the save path, if needed.
    if save:
        save_path = path_constructor(ext=ext, filepath=filepath, 
            save_dir=save_dir, sep_by_detector=sep_by_detector, 
            detector=detector, etc=etc, description='spectrum')

    # Adding a buffer of zeros around the 'gain' array. (Note that the
    # indices will now be shifted over by one.)
    gain_buffed = np.zeros((34, 34))
    gain_buffed[1:33, 1:33] = gain
    gain = gain_buffed

    # Get data from gamma flood FITS file
    with fits.open(filepath) as file:
        data = file[1].data

    # 'START' and 'END' denote the indices between which 'data['TEMP']'
    # takes on a resonable value. START is the first index with a 
    # temperature greater than -20 C, and END is the last such index.
    temp_mask = data['TEMP'] > -20
    START = np.argmax(temp_mask)
    END = len(temp_mask) - np.argmax(temp_mask[::-1])

    # If there's gain data then correct the spectrum
    # PH_COM is a list of length 9 corresponding to the charge in pixels 
    # surrounding the event.
    #
    # PH_COM -> gain correct -> sum positive elements in the 3x3 array -> event in energy units
    energies = []
    for event in data[START:END]:
        row = event['RAWY']
        col = event['RAWX']
        temp = event['PH_COM'].reshape(3, 3)
        mask = (temp > 0).astype(int)
        energy_list.append(np.sum(
            np.multiply(
                np.multiply(mask, temp), 
                gain[row:row + 3, col:col + 3])
            )
        )

    # Binning by energy
    counts, edges = np.histogram(energies, bins=bins, range=energy_range)

    # Getting the midpoint of the edges of each bin.
    midpoints = (edges[:-1] + edges[1:]) / 2

    # Consolidating 'counts' and 'midpoints' into a 2D array 'spectrum'.
    spectrum = np.empty((2, counts.size))
    spectrum[0, :] = counts
    spectrum[1, :] = midpoints

    if save:
        np.savetxt(save_path, spectrum)

    return spectrum


def plot_spectrum(spectrum, line, title='Spectrum', save=True, 
    path_constructor=construct_path, filepath='', etc='', ext='.eps', 
    save_dir='', sep_by_detector=False, detector=''):
    '''
    Fits and plots the spectrum returned from 'get_spectrum'.
    '''
    maxchannel = 10000


    # Constructing a save path, if needed
    if save:
        save_path = path_constructor(ext=ext, filepath=filepath, 
            save_dir=save_dir, sep_by_detector=sep_by_detector, 
            detector=detector, etc=etc, description='energy_spectrum')

    # 'centroid' is the bin with the most counts
    centroid = np.argmax(spectrum[0, 1000:]) + 1000
    # Fit in an asymetrical domain about the centroid to avoid 
    # low energy tails.
    fit_channels = np.arange(centroid - 80, centroid + 150)
    # Do the actual fitting.
    g_init = models.Gaussian1D(amplitude=spectrum[0, centroid], 
        mean=centroid, stddev=75)
    fit_g = fitting.LevMarLSQFitter()
    g = fit_g(g_init, fit_channels, spectrum[0, fit_channels])

    print(np.diag(fit_g.fit_info['param_cov']))

    sigma_err = np.diag(fit_g.fit_info['param_cov'])[2]
    fwhm_err = 2 * np.sqrt(2 * np.log(2)) * sigma_err
    mean_err = np.diag(fit_g.fit_info['param_cov'])[1]
    frac_err = np.sqrt(
        np.square(fwhm_err) 
        + np.square(g.fwhm * mean_err / g.mean)
    ) / g.mean

    print(g.fwhm / g.mean)
    print(frac_err)
    print(line.energy * g.fwhm / g.mean)
    print(frac_err * line.energy)

    # Displaying the FWHM on the spectrum plot, with error.
    display_fwhm = str(int(round(line.energy * 1000 * g.fwhm / g.mean, 0)))
    display_err  = str(int(round(frac_err * line.energy * 1000)))

    plt.text(70, spectrum[0, centroid] * 3 / 5, r'$\mathrm{FWHM}=$' 
        +  display_fwhm + r'$\pm$' + display_err + ' eV', 
        fontsize=13)

    plt.plot(spectrum[1, :-1], spectrum[0], label = r'${}^{241}{\rm Am}$')
    plt.plot(spectrum[1, fit_channels], g(fit_channels), 
        label = 'Gaussian fit')
    plt.xlabel('Energy (keV)')
    plt.ylabel('Counts')
    plt.legend()

    plt.title(title)
    plt.tight_layout()
    if save:
        plt.savefig(save_path)
    plt.show()
    plt.close()


# If this file is run from the terminal, the code below will run all the 
# above functions in a pipeline.
if __name__ == '__main__':

    # Temporary value. Will change to request input at command prompt.
    filepath = '20170315_H100_gamma_Am241_-10C.0V.fits'

    # Generating data
    count_map = count_map(filepath)
    gain = quick_gain(filepath, 'Am241', detector='H100')
    energy_list = gain_correct(filepath, gain)

    # Plotting and fitting data
    pixel_map_counts = pixel_map_counts(count_map, title='Count Map')
    pixel_map_gain = pixel_map_gain(gain, title='Gain Map')
    histogram = plot_count_hist(count_map)

    # Displaying plots
    bokeh.io.output_file('plots.html')
    bokeh.io.show(pixel_map_gain)
    bokeh.io.show(pixel_map)
    bokeh.io.show(histogram)
