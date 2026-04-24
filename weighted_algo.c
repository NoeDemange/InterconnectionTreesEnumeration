#define _POSIX_C_SOURCE 200809L

#include <ctype.h>
#include <errno.h>
#include <float.h>
#include <limits.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

static volatile sig_atomic_t time_limit_hit = 0;
static long long g_max_rows_per_mode = 0;
static int g_row_cap_hit = 0;
/**
 * @brief POSIX signal handler that records when the wall-clock limit is reached.
 *
 * @param sig Signal identifier provided by the runtime (unused).
 */
static void handle_time_limit(int sig) {
    (void)sig;
    time_limit_hit = 1;
}

/** Global counter tracking how many interconnection trees have been enumerated. */
long long int compteurSol = 0;

typedef struct {
    double *values;
    long long size;
    long long capacity;
} WeightList;

typedef enum {
    RUN_MODE_ALL = 0,
    RUN_MODE_NON_ORDERED = 1,
    RUN_MODE_SORTED_AT_END = 2,
    RUN_MODE_ORDERED = 3
} RunMode;

typedef enum {
    PART_SELECTION_MAX_VERTICES = 0,       /* Maximum vertices, tie-break by min_first_edge */
    PART_SELECTION_MIN_AVG_WEIGHT = 1,     /* Part with the minimum average edge weight */
    PART_SELECTION_MIN_FIRST_EDGE = 2,     /* Part whose lightest edge is smallest */
    PART_SELECTION_MIN_VERTICES = 3        /* Minimum vertices, tie-break by min_first_edge */
} PartSelectionMethod;

static const char *run_mode_name(RunMode mode);
static int parse_run_mode(const char *value, RunMode *mode);
static int parse_part_selection_method(const char *value, PartSelectionMethod *method);

static int compare_double_ascending(const void *a, const void *b) {
    const double da = *(const double *)a;
    const double db = *(const double *)b;
    if (da < db) {
        return -1;
    }
    if (da > db) {
        return 1;
    }
    return 0;
}

static void weight_list_init(WeightList *list) {
    list->values = NULL;
    list->size = 0;
    list->capacity = 0;
}

static int weight_list_reserve(WeightList *list, long long new_capacity) {
    if (new_capacity <= list->capacity) {
        return 1;
    }

    if (new_capacity < 16) {
        new_capacity = 16;
    }

    size_t max_entries = SIZE_MAX / sizeof(double);
    if ((unsigned long long)new_capacity > (unsigned long long)max_entries) {
        return 0;
    }

    double *new_values = realloc(list->values, (size_t)new_capacity * sizeof(double));
    if (new_values == NULL) {
        return 0;
    }

    list->values = new_values;
    list->capacity = new_capacity;
    return 1;
}

static int weight_list_reserve_exact(WeightList *list, long long exact_capacity) {
    if (exact_capacity < 0) {
        return 0;
    }

    free(list->values);
    list->values = NULL;
    list->size = 0;
    list->capacity = 0;

    if (exact_capacity == 0) {
        return 1;
    }

    size_t max_entries = SIZE_MAX / sizeof(double);
    if ((unsigned long long)exact_capacity > (unsigned long long)max_entries) {
        return 0;
    }

    list->values = malloc((size_t)exact_capacity * sizeof(double));
    if (list->values == NULL) {
        return 0;
    }

    list->capacity = exact_capacity;
    return 1;
}

static int weight_list_append(WeightList *list, double weight) {
    if (list->size == list->capacity) {
        long long next_capacity = (list->capacity == 0) ? 16 : (list->capacity * 2);
        if (!weight_list_reserve(list, next_capacity)) {
            return 0;
        }
    }

    list->values[list->size++] = weight;
    return 1;
}

static void weight_list_free(WeightList *list) {
    free(list->values);
    list->values = NULL;
    list->size = 0;
    list->capacity = 0;
}

static int safe_mul_ull(unsigned long long a, unsigned long long b, unsigned long long *res) {
    if (a != 0 && b > ULLONG_MAX / a) {
        return 0;
    }
    *res = a * b;
    return 1;
}

static unsigned long long compute_number_interconnection_trees(int V, int k, const int Vi[]) {
    unsigned long long result = 1;
    unsigned long long temp = 0;
    int n = V - k;

    for (int j = 0; j <= k - 3; j++) {
        if (!safe_mul_ull(result, (unsigned long long)(n - j), &temp)) {
            fprintf(stderr, "Overflow detected during falling factorial\n");
            exit(EXIT_FAILURE);
        }
        result = temp;
    }

    for (int i = 0; i < k; i++) {
        if (!safe_mul_ull(result, (unsigned long long)Vi[i], &temp)) {
            fprintf(stderr, "Overflow detected during Vi product\n");
            exit(EXIT_FAILURE);
        }
        result = temp;
    }

    return result;
}

static int append_weight_list_csv(FILE *out, RunMode mode, const WeightList *weights) {
    const char *mode_name = run_mode_name(mode);
    for (long long i = 0; i < weights->size; ++i) {
        fprintf(out, "%s,%lld,%.12g\n", mode_name, i + 1, weights->values[i]);
    }
    return 1;
}

static FILE *open_weight_csv(const char *output_path) {
    return fopen(output_path, "w");
}

static int write_weight_csv_header(FILE *out) {
    return fprintf(out, "mode,rank,total_weight\n") >= 0;
}

static int write_weight_sequences_csv(const char *output_path,
                                      RunMode mode,
                                      const WeightList *weights) {
    FILE *out = fopen(output_path, "a");
    if (out == NULL) {
        return 0;
    }

    (void)mode;
    if (!append_weight_list_csv(out, mode, weights)) {
        fclose(out);
        return 0;
    }
    fclose(out);
    return 1;
}

static void configure_wallclock_timer(double time_limit_sec) {
    struct itimerval timer;
    memset(&timer, 0, sizeof(timer));
    if (time_limit_sec > 0.0) {
        double whole_seconds = floor(time_limit_sec);
        timer.it_value.tv_sec = (time_t)whole_seconds;
        timer.it_value.tv_usec = (suseconds_t)((time_limit_sec - whole_seconds) * 1e6);
    }
    setitimer(ITIMER_REAL, &timer, NULL);
}

static double elapsed_ms_between(const struct timespec *start, const struct timespec *end) {
    double delta_sec = (double)(end->tv_sec - start->tv_sec);
    double delta_nsec = (double)(end->tv_nsec - start->tv_nsec);
    return delta_sec * 1000.0 + delta_nsec / 1e6;
}

/**
 * @brief Optional geometric information stored for each vertex.
 */
typedef struct {
    double coords[3];
    int has_coords; // Flag indicating whether coordinates are available: 1 = yes, 0 = no
} VertexAttributes;

/**
 * @brief Load the partition description and optional vertex coordinates from disk.
 *
 * The routine reads the problem instance formatted as "<num_vertices> <num_components>"
 * followed by one line per vertex containing either "component" or
 * "component x y z". It fills the component assignment array `S`, per-component
 * counts `C`, and (optionally) the coordinate metadata in `vertex_attrs`.
 * Any malformed input triggers an error message and immediate termination.
 *
 * @param[out] S                Array mapping each vertex to its component id.
 * @param[out] C                Array that stores how many vertices lie in each component.
 * @param[out] vertex_attrs     Optional coordinates/flags for each vertex.
 * @param[out] num_vertex       Total number of vertices parsed from the file header.
 * @param[out] num_components   Total number of components parsed from the file header.
 * @param[in]  input_file       Path to the instance file to parse.
 */
static void load_partition(int** S, int** C, VertexAttributes** vertex_attrs, int* num_vertex, int* num_components, const char* input_file) {
    FILE *file = fopen(input_file, "r");
    if (file == NULL) {
        perror("Failed to open input file");
        exit(EXIT_FAILURE);
    }

    if (fscanf(file, "%d %d", num_vertex, num_components) != 2) {
        fprintf(stderr, "Malformed header in %s\n", input_file);
        fclose(file);
        exit(EXIT_FAILURE);
    }

    if (*num_vertex <= 0 || *num_components <= 0) {
        fprintf(stderr, "Invalid sizes in %s: vertices=%d components=%d\n", input_file, *num_vertex, *num_components);
        fclose(file);
        exit(EXIT_FAILURE);
    }

    *S = malloc((size_t)(*num_vertex) * sizeof(int));
    if (*S == NULL) {
        fprintf(stderr, "Failed to allocate vertex-to-component array\n");
        fclose(file);
        exit(EXIT_FAILURE);
    }

    *C = calloc((size_t)(*num_components), sizeof(int));
    if (*C == NULL) {
        fprintf(stderr, "Failed to allocate component sizes\n");
        fclose(file);
        exit(EXIT_FAILURE);
    }

    *vertex_attrs = malloc((size_t)(*num_vertex)*sizeof(VertexAttributes));
    if (*vertex_attrs == NULL) {
        fprintf(stderr, "Failed to allocate vertex attribute array\n");
        fclose(file);
        exit(EXIT_FAILURE);
    }

    char line[512];
    int vertex_index = 0;
    while (vertex_index < *num_vertex) {
        if (fgets(line, sizeof(line), file) == NULL) {
            fprintf(stderr, "Unexpected end of file while reading vertex %d in %s\n", vertex_index, input_file);
            fclose(file);
            exit(EXIT_FAILURE);
        }

        char *cursor = line;
        while (*cursor && isspace((unsigned char)*cursor)) {
            cursor++;
        }
        if (*cursor == '\0') {
            continue; // Skip blank lines.
        }

        int component = -1;
        double x = 0.0, y = 0.0, z = 0.0;
        int parsed = sscanf(cursor, "%d %lf %lf %lf", &component, &x, &y, &z);
        if (parsed != 1 && parsed != 4) {
            fprintf(stderr, "Malformed component/coordinate assignment at vertex %d in %s\n", vertex_index, input_file);
            fclose(file);
            exit(EXIT_FAILURE);
        }

        if (component < 0 || component >= *num_components) {
            fprintf(stderr, "Component index %d out of bounds for %s\n", component, input_file);
            fclose(file);
            exit(EXIT_FAILURE);
        }

        (*S)[vertex_index] = component;
        (*C)[component]++;
        (*vertex_attrs)[vertex_index].has_coords = (parsed == 4);
        if (parsed == 4) {
            (*vertex_attrs)[vertex_index].coords[0] = x;
            (*vertex_attrs)[vertex_index].coords[1] = y;
            (*vertex_attrs)[vertex_index].coords[2] = z;
        }
        vertex_index++;
    }

    fclose(file);
}

////// Helper functions for in-place updates with backup and restore //////
// Update vertex assignments in place while saving enough state to restore them later.
static int UpdateVertex(int* S, int S1, int S2, int num_vertex, int* backup_S1, int* backup_S2, int* affected_indices, int* affected_count) {
    int min, max;

    if (S[S1] < S[S2]) {
        min = S[S1];
        max = S[S2];
    } else {
        min = S[S2];
        max = S[S1];
    }

    *backup_S1 = S[S1];
    *backup_S2 = S[S2];

    // Store the indices of vertices that are modified.
    *affected_count = 0;
    for (int i = 0; i < num_vertex; i++) {
        if (S[i] == max) {
            affected_indices[*affected_count] = i;
            (*affected_count)++;
            S[i] = min;  // Replace max with min.
        }
    }

    // Mark the selected vertices as -1.
    S[S1] = -1;
    S[S2] = -1;

    return max; // Return the original max value for restoration.
}

// Restore the vertex array after modification.
static void RestoreVertex(int* S, int S1, int S2, int backup_S1, int backup_S2, int* affected_indices, int affected_count, int backup_max) {
    // Restore vertices S1 and S2.
    S[S1] = backup_S1;
    S[S2] = backup_S2;

    // Restore the affected vertices that were changed from max to min.
    for (int i = 0; i < affected_count; i++) {
        S[affected_indices[i]] = backup_max;
    }
}

// Update the component-size array in place while keeping backup values.
static void UpdateSubset(int* C, int P1, int P2, int* backup_C_max, int* backup_C_min) {
    int min, max;

    if (P1 < P2) {
        min = P1;
        max = P2;
    } else {
        min = P2;
        max = P1;
    }

    *backup_C_min = C[min];
    *backup_C_max = C[max];

    C[min] = C[min] + C[max] - 2;
    C[max] = 0;
}

// Restore the component-size array after modification.
static void RestoreSubset(int* C, int P1, int P2, int backup_C_max, int backup_C_min) {
    int min, max;

    if (P1 < P2) {
        min = P1;
        max = P2;
    } else {
        min = P2;
        max = P1;
    }

    C[min] = backup_C_min;
    C[max] = backup_C_max;
}

static void Ban_s_Vertex(int* S, int s, int* backup_S) {
    *backup_S = S[s];
    S[s] = -1;
}

static void RestoreBan_s_Vertex(int* S, int s, int backup_S) {
    S[s] = backup_S;
}

static void Ban_s_Subset(int* C, int p, int* backup_C) {
    *backup_C = C[p];
    C[p]--;
}

static void RestoreBan_s_Subset(int* C, int p, int backup_C) {
    C[p] = backup_C;
}

static WeightList *g_active_weight_list = NULL;

static int weight_collection_limit_reached(void) {
    if (g_active_weight_list == NULL) {
        return 0;
    }
    if (g_max_rows_per_mode <= 0) {
        return 0;
    }
    return g_active_weight_list->size >= g_max_rows_per_mode;
}

///// Main enumeration function (non-ordered version) ////
void NonOrderedEnumArbresInterconnection(int* S, int* C, int* interTree, int num_vertex, int k, int K, int s, int marge, double (*edge_weight)[num_vertex], double total_weight) {
    if (time_limit_hit) {
        return;
    }
    if (weight_collection_limit_reached()) {
        g_row_cap_hit = 1;
        return;
    }

    if (K >= (k - 1)) {
        if (weight_collection_limit_reached()) {
            g_row_cap_hit = 1;
            return;
        }
        if (g_active_weight_list != NULL && !weight_list_append(g_active_weight_list, total_weight)) {
            fprintf(stderr, "Failed to append solution weight\n");
            exit(EXIT_FAILURE);
        }
        // Optional: print the current interconnection tree and its weight for debugging.
        // for (int i = 0; i < K * 2; i += 2) {
        //     printf("Edge: %d - %d, Weight: %f\n", interTree[i], interTree[i + 1], edge_weight[interTree[i]][interTree[i + 1]]);
        // }
        // printf("Total Weight: %f\n", total_weight);

        compteurSol++;
        return;
    }

    int next_s;
    for (int v = s + 1; v < num_vertex; v++) {
        if (time_limit_hit || weight_collection_limit_reached()) {
            g_row_cap_hit = weight_collection_limit_reached();
            return;
        }
        int comp_sum = C[S[s]] + C[S[v]] - 2;
        if ((S[s] != -1) && (S[v] != -1) && (S[s] != S[v]) && ((K == (k - 2)) || (comp_sum > 0))) {
            interTree[K * 2] = s;
            interTree[K * 2 + 1] = v;

            int backup_S1, backup_S2, backup_max;
            int affected_indices[num_vertex];
            int affected_count = 0;
            int backup_C_max, backup_C_min;

            UpdateSubset(C, S[s], S[v], &backup_C_max, &backup_C_min);
            backup_max = UpdateVertex(S, s, v, num_vertex, &backup_S1, &backup_S2, affected_indices, &affected_count);

            next_s = s;
            do {
                next_s = next_s + 1;
            } while (next_s < num_vertex && S[next_s] == -1);

            NonOrderedEnumArbresInterconnection(S, C, interTree, num_vertex, k, K + 1, next_s, marge, edge_weight, total_weight + edge_weight[s][v]);

            RestoreVertex(S, s, v, backup_S1, backup_S2, affected_indices, affected_count, backup_max);
            RestoreSubset(C, S[s], S[v], backup_C_max, backup_C_min);
        }
    }

    next_s = s;
    if ((marge > 0) && (C[S[s]] > 0)) {
        int backup_S, backup_C;
        Ban_s_Subset(C, S[s], &backup_C);
        Ban_s_Vertex(S, s, &backup_S);
        do {
            next_s = next_s + 1;
        } while (next_s < num_vertex && S[next_s] == -1);
        NonOrderedEnumArbresInterconnection(S, C, interTree, num_vertex, k, K, next_s, marge - 1, edge_weight, total_weight);
        RestoreBan_s_Vertex(S, s, backup_S);
        RestoreBan_s_Subset(C, S[s], backup_C);
    }
}


///// Ordered enumeration ////
// Type used to store weighted edges.
typedef struct {
    int edge_u;
    int edge_v;
    double edge_weight;
} WeightedEdge;

static int compare_weighted_edges(const void* a, const void* b) {
    const WeightedEdge* edge_a = (const WeightedEdge*)a;
    const WeightedEdge* edge_b = (const WeightedEdge*)b;
    if (edge_a->edge_weight < edge_b->edge_weight) {
        return -1;
    }
    if (edge_a->edge_weight > edge_b->edge_weight) {
        return 1;
    }
    return 0;
}

// Type used to store a partition together with its candidate edges.
typedef struct{
    int num_edges;
    int allocated_edges; // Allocated size of the edge array.
    WeightedEdge* edges;
} Part;

// Build the next main partition after merging two components through edge (s, v).
Part updateRootPartUsingEdge(Part main_part, const Part* parts, int* S, int s, int id_part_of_v){
    Part new_part;
    new_part.num_edges = 0;
    new_part.allocated_edges = main_part.num_edges + parts[id_part_of_v].num_edges - 1;
    new_part.edges = malloc((size_t)new_part.allocated_edges * sizeof(WeightedEdge));
    if (new_part.edges == NULL) {
        fprintf(stderr, "Failed to allocate memory for new partition edges\n");
        exit(EXIT_FAILURE);
    }

    int id_part = S[s];
    // Copy edges from the original partition, excluding edges internal to the merged component.
    for (int i = 0; i < main_part.num_edges; i++) {
        WeightedEdge e = main_part.edges[i];
        if (!(S[e.edge_u] == id_part && S[e.edge_v] == id_part)) {
            new_part.edges[new_part.num_edges++] = e;
        }
    }

    // Add edges from the partition of v that are not already present in the new partition.
    Part part_v = parts[id_part_of_v];
    for (int i = 0; i < part_v.num_edges; i++) {
        WeightedEdge e = part_v.edges[i];
        if (!(S[e.edge_u] == id_part && S[e.edge_v] == id_part)) {
            new_part.edges[new_part.num_edges++] = e;
        }
    }

    // Sort edges by weight for the ordered enumeration.
    qsort(new_part.edges, (size_t)new_part.num_edges, sizeof(WeightedEdge), compare_weighted_edges);
    return new_part;
}

Part banEdgeFromPart(Part main_part){
    Part new_part;
    new_part.num_edges = main_part.num_edges - 1;
    new_part.allocated_edges = new_part.num_edges;
    new_part.edges = malloc((size_t)new_part.allocated_edges * sizeof(WeightedEdge));
    if (new_part.edges == NULL) {
        fprintf(stderr, "Failed to allocate memory for new partition edges\n");
        exit(EXIT_FAILURE);
    }

    // Copy edges from the original partition, excluding the first edge (the edge to ban).
    for (int i = 1; i < main_part.num_edges; i++) {
        new_part.edges[i - 1] = main_part.edges[i];
    }

    return new_part;
}

// Main enumeration function for the ordered version.
// No pruning is implemented here, so this version can be very slow on large instances.
void OrderedEnumArbresInterconnection(int* S, int* C,Part main_part, const Part* parts, int* interTree, int num_vertex, int k, int K, double total_weight) {
    // Time limit check.
    if (time_limit_hit) {
        return;
    }
    if (weight_collection_limit_reached()) {
        g_row_cap_hit = 1;
        return;
    }

    // Base case: if we have selected k-1 edges, the interconnection tree is complete.
    if (K >= (k - 1)) {
        if (weight_collection_limit_reached()) {
            g_row_cap_hit = 1;
            return;
        }
        if (g_active_weight_list != NULL && !weight_list_append(g_active_weight_list, total_weight)) {
            fprintf(stderr, "Failed to append solution weight\n");
            exit(EXIT_FAILURE);
        }
        // Optional: print the current interconnection tree and its weight for debugging.
        // for (int i = 0; i < K * 2; i += 2) {
        //     printf("Edge: %d - %d, Weight: %f\n", interTree[i], interTree[i + 1], edge_weight[interTree[i]][interTree[i + 1]]);
        // }
        // printf("Total Weight: %f\n", total_weight);
        compteurSol++;
        return;
    }

    if (main_part.num_edges <= 0) {
        return;
    }

    WeightedEdge e = main_part.edges[0];
    int s = e.edge_u;
    int v = e.edge_v;
    if ((S[s] != -1) && (S[v] != -1) && (S[s] != S[v])) {
        interTree[K * 2] = s;
        interTree[K * 2 + 1] = v;

        int backup_S1, backup_S2, backup_max;
        int affected_indices[num_vertex];
        int affected_count = 0;
        int backup_C_max, backup_C_min;

        int id_part_of_v = S[v];

        // Prepare for the recursive call by updating the vertex and component arrays, while keeping backups for restoration.
        UpdateSubset(C, S[s], S[v], &backup_C_max, &backup_C_min);
        backup_max = UpdateVertex(S, s, v, num_vertex, &backup_S1, &backup_S2, affected_indices, &affected_count);
        // Create the new partition for the recursive call by merging the two parts, removing internal edges, and sorting by weight.
        Part new_main_part = updateRootPartUsingEdge(main_part, parts, S, s, id_part_of_v);
        // Recursive call to explore the next level of the search tree.
        OrderedEnumArbresInterconnection(S, C, new_main_part, parts, interTree, num_vertex, k, K + 1, total_weight + e.edge_weight);
        // After the recursive call returns, restore the vertex and component arrays before exploring the next edge.
        RestoreVertex(S, s, v, backup_S1, backup_S2, affected_indices, affected_count, backup_max);
        RestoreSubset(C, S[s], S[v], backup_C_max, backup_C_min);
        free(new_main_part.edges);
    }
    if (main_part.num_edges > 1) { // If more than one edge remains, also explore the branch that bans edge e.
        Part new_main_part = banEdgeFromPart(main_part); // Create the recursive branch with edge e removed.
        OrderedEnumArbresInterconnection(S, C, new_main_part, parts, interTree, num_vertex, k, K, total_weight);
        free(new_main_part.edges);
    }
}

typedef struct {
    long long solution_count;
    double elapsed_ms;
    int timed_out;
    int row_cap_hit;
} RunMetrics;

static const char *run_mode_name(RunMode mode) {
    switch (mode) {
        case RUN_MODE_NON_ORDERED:
            return "non_ordered";
        case RUN_MODE_SORTED_AT_END:
            return "sorted_at_end";
        case RUN_MODE_ORDERED:
            return "ordered";
        case RUN_MODE_ALL:
        default:
            return "all";
    }
}

static int parse_run_mode(const char *value, RunMode *mode) {
    if (strcmp(value, "all") == 0) {
        *mode = RUN_MODE_ALL;
        return 1;
    }
    if (strcmp(value, "non_ordered") == 0 || strcmp(value, "non-ordered") == 0 || strcmp(value, "non") == 0) {
        *mode = RUN_MODE_NON_ORDERED;
        return 1;
    }
    if (strcmp(value, "sorted_at_end") == 0 || strcmp(value, "sorted-at-end") == 0 || strcmp(value, "sorted") == 0) {
        *mode = RUN_MODE_SORTED_AT_END;
        return 1;
    }
    if (strcmp(value, "ordered") == 0) {
        *mode = RUN_MODE_ORDERED;
        return 1;
    }
    return 0;
}

static int parse_part_selection_method(const char *value, PartSelectionMethod *method) {
    if (strcmp(value, "max_vertices") == 0) {
        *method = PART_SELECTION_MAX_VERTICES;
        return 1;
    }
    if (strcmp(value, "min_avg_weight") == 0) {
        *method = PART_SELECTION_MIN_AVG_WEIGHT;
        return 1;
    }
    if (strcmp(value, "min_first_edge") == 0) {
        *method = PART_SELECTION_MIN_FIRST_EDGE;
        return 1;
    }
    if (strcmp(value, "min_vertices") == 0) {
        *method = PART_SELECTION_MIN_VERTICES;
        return 1;
    }
    return 0;
}

static int lexicographic_edge_compare(const Part *a, const Part *b) {
    int common = (a->num_edges < b->num_edges) ? a->num_edges : b->num_edges;
    for (int i = 0; i < common; i++) {
        double wa = a->edges[i].edge_weight;
        double wb = b->edges[i].edge_weight;
        if (wa < wb) {
            return -1;
        }
        if (wa > wb) {
            return 1;
        }
    }

    if (a->num_edges < b->num_edges) {
        return -1;
    }
    if (a->num_edges > b->num_edges) {
        return 1;
    }
    return 0;
}

/**
 * @brief Select the main part based on the chosen selection method.
 * 
 * The method can be:
 *  - PART_SELECTION_MAX_VERTICES: Use the part with the maximum number of vertices
 *  - PART_SELECTION_MIN_AVG_WEIGHT: Use the part with minimum average edge weight (total_weight / num_edges)
 *  - PART_SELECTION_MIN_FIRST_EDGE: Use the part with the smallest first edge (lexicographic tie-break)
 *  - PART_SELECTION_MIN_VERTICES: Use the part with the minimum number of vertices
 *
 * @param parts Array of parts
 * @param num_components Number of components (and parts)
 * @param C Array with the number of vertices in each component
 * @param method The selection method to use
 * @return Index of the selected part
 */
static int select_main_part(const Part *parts, int num_components, const int *C, PartSelectionMethod method) {
    if (num_components <= 0) {
        return 0;
    }

    switch (method) {
        case PART_SELECTION_MAX_VERTICES: {
            int max_index = 0;
            int max_vertices = C[0];
            for (int i = 1; i < num_components; i++) {
                if (C[i] > max_vertices) {
                    max_vertices = C[i];
                    max_index = i;
                } else if (C[i] == max_vertices &&
                           lexicographic_edge_compare(&parts[i], &parts[max_index]) < 0) {
                    max_index = i;
                }
            }
            return max_index;
        }

        case PART_SELECTION_MIN_AVG_WEIGHT: {
            int min_index = 0;
            double min_avg_weight = DBL_MAX;

            if (parts[0].num_edges > 0) {
                double total_weight = 0.0;
                for (int e = 0; e < parts[0].num_edges; e++) {
                    total_weight += parts[0].edges[e].edge_weight;
                }
                min_avg_weight = total_weight / parts[0].num_edges;
            }

            for (int i = 1; i < num_components; i++) {
                if (parts[i].num_edges > 0) {
                    double total_weight = 0.0;
                    for (int e = 0; e < parts[i].num_edges; e++) {
                        total_weight += parts[i].edges[e].edge_weight;
                    }
                    double avg_weight = total_weight / parts[i].num_edges;
                    if (avg_weight < min_avg_weight) {
                        min_avg_weight = avg_weight;
                        min_index = i;
                    }
                }
            }
            return min_index;
        }

        case PART_SELECTION_MIN_FIRST_EDGE: {
            int best_index = 0;
            for (int i = 1; i < num_components; i++) {
                if (lexicographic_edge_compare(&parts[i], &parts[best_index]) < 0) {
                    best_index = i;
                }
            }
            return best_index;
        }

        case PART_SELECTION_MIN_VERTICES: {
            int best_index = 0;
            int best_vertices = C[0];

            for (int i = 1; i < num_components; i++) {
                if (C[i] < best_vertices) {
                    best_vertices = C[i];
                    best_index = i;
                } else if (C[i] == best_vertices &&
                           lexicographic_edge_compare(&parts[i], &parts[best_index]) < 0) {
                    best_index = i;
                }
            }
            return best_index;
        }

        default:
            return 0;
    }
}

static void reset_partition_state(int *S_dst, int *C_dst, const int *S_src, const int *C_src, int num_vertex, int num_components) {
    memcpy(S_dst, S_src, (size_t)num_vertex * sizeof(int));
    memcpy(C_dst, C_src, (size_t)num_components * sizeof(int));
}

static int build_parts_from_partition(const int *S, const int *C, int num_vertex, int num_components,
                                      double (*edge_weight)[num_vertex], Part **parts_out) {
    Part *parts = calloc((size_t)num_components, sizeof(Part));
    if (parts == NULL) {
        return 0;
    }

    for (int i = 0; i < num_components; i++) {
        parts[i].num_edges = C[i] * (num_vertex - C[i]);
        parts[i].allocated_edges = parts[i].num_edges;
        parts[i].edges = malloc((size_t)parts[i].num_edges * sizeof(WeightedEdge));
        if (parts[i].edges == NULL) {
            for (int j = 0; j < i; ++j) {
                free(parts[j].edges);
            }
            free(parts);
            return 0;
        }

        int edge_index = 0;
        for (int v1 = 0; v1 < num_vertex; v1++) {
            if (S[v1] == i) {
                for (int v2 = 0; v2 < num_vertex; v2++) {
                    if (S[v2] != i) {
                        parts[i].edges[edge_index].edge_u = v1;
                        parts[i].edges[edge_index].edge_v = v2;
                        parts[i].edges[edge_index].edge_weight = edge_weight[v1][v2];
                        edge_index++;
                    }
                }
            }
        }

        qsort(parts[i].edges, (size_t)parts[i].num_edges, sizeof(WeightedEdge), compare_weighted_edges);
    }

    *parts_out = parts;
    return 1;
}

static void free_parts(Part *parts, int num_components) {
    if (parts == NULL) {
        return;
    }
    for (int i = 0; i < num_components; ++i) {
        free(parts[i].edges);
    }
    free(parts);
}

static RunMetrics run_non_ordered_mode(int *S_work, int *C_work, const int *S_initial, const int *C_initial,
                                       int *interTree, int num_vertex, int num_components,
                                       double (*edge_weight)[num_vertex], double time_limit_sec,
                                       WeightList *target_list) {
    RunMetrics metrics = {0, 0.0, 0, 0};

    reset_partition_state(S_work, C_work, S_initial, C_initial, num_vertex, num_components);
    compteurSol = 0;
    time_limit_hit = 0;
    g_row_cap_hit = 0;
    g_active_weight_list = target_list;

    configure_wallclock_timer(time_limit_sec);
    struct timespec start = {0}, end = {0};
    clock_gettime(CLOCK_MONOTONIC, &start);
    NonOrderedEnumArbresInterconnection(S_work, C_work, interTree, num_vertex, num_components, 0, 0,
                                       num_vertex - (2 * (num_components - 1)), edge_weight, 0.0);
    clock_gettime(CLOCK_MONOTONIC, &end);
    configure_wallclock_timer(0.0);

    metrics.solution_count = compteurSol;
    metrics.elapsed_ms = elapsed_ms_between(&start, &end);
    metrics.timed_out = time_limit_hit;
    metrics.row_cap_hit = g_row_cap_hit;
    return metrics;
}

static RunMetrics run_ordered_mode(int *S_work, int *C_work, const int *S_initial, const int *C_initial,
                                   int *interTree, int num_vertex, int num_components,
                                   double (*edge_weight)[num_vertex], double time_limit_sec,
                                   WeightList *target_list, PartSelectionMethod part_selection) {
    RunMetrics metrics = {0, 0.0, 0, 0};
    Part *parts = NULL;

    reset_partition_state(S_work, C_work, S_initial, C_initial, num_vertex, num_components);
    if (!build_parts_from_partition(S_work, C_work, num_vertex, num_components, edge_weight, &parts)) {
        fprintf(stderr, "Failed to initialize parts for ordered enumeration\n");
        exit(EXIT_FAILURE);
    }

    compteurSol = 0;
    time_limit_hit = 0;
    g_row_cap_hit = 0;
    g_active_weight_list = target_list;

    configure_wallclock_timer(time_limit_sec);
    struct timespec start = {0}, end = {0};
    clock_gettime(CLOCK_MONOTONIC, &start);
    int main_part_index = select_main_part(parts, num_components, C_work, part_selection);
    fprintf(stderr, "SELECTED_PART_ID=%d\n", main_part_index);
    OrderedEnumArbresInterconnection(S_work, C_work, parts[main_part_index], parts, interTree, num_vertex, num_components, 0, 0.0);
    clock_gettime(CLOCK_MONOTONIC, &end);
    configure_wallclock_timer(0.0);

    metrics.solution_count = compteurSol;
    metrics.elapsed_ms = elapsed_ms_between(&start, &end);
    metrics.timed_out = time_limit_hit;
    metrics.row_cap_hit = g_row_cap_hit;

    free_parts(parts, num_components);
    return metrics;
}

//// Main function

int main(int argc, char** argv) {
    if (argc < 2 || argc > 8) {
        fprintf(stderr, "Usage: %s <input_file> [time_limit_seconds|mode] [output_csv] [random_seed] [mode] [max_rows_per_mode] [part_selection]\n", argv[0]);
        fprintf(stderr, "Modes: all, non_ordered, sorted_at_end, ordered\n");
        fprintf(stderr, "Part selection (for ordered mode): max_vertices, min_avg_weight, min_first_edge, min_vertices\n");
        return EXIT_FAILURE;
    }

    double time_limit_sec = 0.0;
    RunMode selected_mode = RUN_MODE_ALL;
    unsigned int random_seed = (unsigned int)time(NULL);
    const char *output_csv = "weights_sequences.csv";
    long long max_rows_per_mode = 0;
    PartSelectionMethod part_selection = PART_SELECTION_MIN_FIRST_EDGE;  /* Default part-selection method. */

    int arg_index = 2;
    if (arg_index < argc) {
        if (parse_run_mode(argv[arg_index], &selected_mode)) {
            arg_index++;
        } else {
            time_limit_sec = atof(argv[arg_index]);
            if (time_limit_sec <= 0.0) {
                fprintf(stderr, "time limit must be > 0\n");
                return EXIT_FAILURE;
            }
            arg_index++;
        }
    }

    if (arg_index < argc) {
        output_csv = argv[arg_index];
        arg_index++;
    }

    if (arg_index < argc) {
        errno = 0;
        char *endptr = NULL;
        unsigned long parsed_seed = strtoul(argv[arg_index], &endptr, 10);
        if (errno != 0 || endptr == argv[arg_index] || *endptr != '\0' || parsed_seed > UINT_MAX) {
            fprintf(stderr, "invalid random_seed: %s\n", argv[arg_index]);
            return EXIT_FAILURE;
        }
        random_seed = (unsigned int)parsed_seed;
        arg_index++;
    }

    if (arg_index < argc && parse_run_mode(argv[arg_index], &selected_mode)) {
        arg_index++;
    }

    if (arg_index < argc) {
        errno = 0;
        char *endptr = NULL;
        long long parsed_max_rows = strtoll(argv[arg_index], &endptr, 10);
        if (errno != 0 || endptr == argv[arg_index] || *endptr != '\0' || parsed_max_rows < 0) {
            fprintf(stderr, "invalid max_rows_per_mode: %s\n", argv[arg_index]);
            return EXIT_FAILURE;
        }
        max_rows_per_mode = parsed_max_rows;
        arg_index++;
    }

    if (arg_index < argc && parse_part_selection_method(argv[arg_index], &part_selection)) {
        arg_index++;
    }

    if (arg_index != argc) {
        fprintf(stderr, "too many arguments\n");
        return EXIT_FAILURE;
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_time_limit;
    sigaction(SIGALRM, &sa, NULL);

    time_limit_hit = 0;
    compteurSol = 0;

    int num_vertex;
    int num_components;   
    
    int *S = NULL;        // Vertex-to-component mapping.
    int *C = NULL;        // Number of vertices in each component.
    VertexAttributes *vertex_attrs = NULL; // Optional coordinates for each vertex.

    char* input_file = argv[1];

    // Load the partition description.
    load_partition(&S, &C, &vertex_attrs, &num_vertex, &num_components, input_file);

    // Compute the minimum and maximum component sizes.
    int min_size = C[0];
    int max_size = C[0];
    for (int i = 1; i < num_components; i++) {
        if (C[i] < min_size) {
            min_size = C[i];
        }
        if (C[i] > max_size) {
            max_size = C[i];
        }
    }

    int *S_initial = malloc((size_t)num_vertex * sizeof(int));
    int *C_initial = malloc((size_t)num_components * sizeof(int));
    int *S_work = malloc((size_t)num_vertex * sizeof(int));
    int *C_work = malloc((size_t)num_components * sizeof(int));
    if (S_initial == NULL || C_initial == NULL || S_work == NULL || C_work == NULL) {
        fprintf(stderr, "Failed to allocate state buffers\n");
        free(S);
        free(C);
        free(vertex_attrs);
        free(S_initial);
        free(C_initial);
        free(S_work);
        free(C_work);
        return EXIT_FAILURE;
    }
    memcpy(S_initial, S, (size_t)num_vertex * sizeof(int));
    memcpy(C_initial, C, (size_t)num_components * sizeof(int));

    double edge_weight[num_vertex][num_vertex];
    srand(random_seed);
    for (int i = 0; i < num_vertex; i++) {
        for (int j = i; j < num_vertex; j++) {
            if (i == j) {
                edge_weight[i][j] = 0.0; // No self-loops.
            } else if (vertex_attrs[i].has_coords && vertex_attrs[j].has_coords) {
                // Use Euclidean distance as the weight when coordinates are available.
                double dx = vertex_attrs[i].coords[0] - vertex_attrs[j].coords[0];
                double dy = vertex_attrs[i].coords[1] - vertex_attrs[j].coords[1];
                double dz = vertex_attrs[i].coords[2] - vertex_attrs[j].coords[2];
                edge_weight[i][j] = edge_weight[j][i] = sqrt(dx * dx + dy * dy + dz * dz);
            } else {
                // Otherwise, assign a random weight between 0.1 and 10.0.
                edge_weight[i][j] = edge_weight[j][i] = 0.1 + 9.9 * ((double)rand() / (double)RAND_MAX);
            }
        }
    }

    int* interTree = malloc((size_t)(2 * (num_components - 1)) * sizeof(int));
    if (interTree == NULL) {
        fprintf(stderr, "Failed to allocate edge buffer\n");
        free(S);
        free(C);
        free(vertex_attrs);
        free(S_initial);
        free(C_initial);
        free(S_work);
        free(C_work);
        return EXIT_FAILURE;
    }

    FILE *csv_out = open_weight_csv(output_csv);
    if (csv_out == NULL) {
        fprintf(stderr, "Failed to open output CSV: %s\n", output_csv);
        free(S);
        free(C);
        free(vertex_attrs);
        free(S_initial);
        free(C_initial);
        free(S_work);
        free(C_work);
        free(interTree);
        return EXIT_FAILURE;
    }
    if (!write_weight_csv_header(csv_out)) {
        fprintf(stderr, "Failed to write CSV header: %s\n", output_csv);
        fclose(csv_out);
        free(S);
        free(C);
        free(vertex_attrs);
        free(S_initial);
        free(C_initial);
        free(S_work);
        free(C_work);
        free(interTree);
        return EXIT_FAILURE;
    }
    fclose(csv_out);

    unsigned long long tree_count_ull = compute_number_interconnection_trees(num_vertex, num_components, C_initial);
    if (tree_count_ull > (unsigned long long)LLONG_MAX) {
        fprintf(stderr, "Cannot preallocate %llu weights: exceeds internal limit\n", tree_count_ull);
        free(S);
        free(C);
        free(vertex_attrs);
        free(S_initial);
        free(C_initial);
        free(S_work);
        free(C_work);
        free(interTree);
        return EXIT_FAILURE;
    }

    long long tree_count = (long long)tree_count_ull;
    long long prealloc_count = tree_count;
    if (max_rows_per_mode > 0 && max_rows_per_mode < prealloc_count) {
        prealloc_count = max_rows_per_mode;
    }
    WeightList weights;
    weight_list_init(&weights);

    if (!weight_list_reserve_exact(&weights, prealloc_count)) {
        fprintf(stderr, "Cannot preallocate weight list\n");
        free(S);
        free(C);
        free(vertex_attrs);
        free(S_initial);
        free(C_initial);
        free(S_work);
        free(C_work);
        free(interTree);
        return EXIT_FAILURE;
    }

    RunMetrics non_ordered_metrics = {0, 0.0, 0, 0};
    RunMetrics sorted_end_metrics = {0, 0.0, 0, 0};
    RunMetrics ordered_metrics = {0, 0.0, 0, 0};
    g_max_rows_per_mode = max_rows_per_mode;

    if (selected_mode == RUN_MODE_ALL || selected_mode == RUN_MODE_NON_ORDERED) {
        weights.size = 0;
        non_ordered_metrics = run_non_ordered_mode(
            S_work, C_work, S_initial, C_initial,
            interTree, num_vertex, num_components,
            edge_weight, time_limit_sec, &weights);
        if (!write_weight_sequences_csv(output_csv, RUN_MODE_NON_ORDERED, &weights)) {
            fprintf(stderr, "Failed to append non_ordered weights to CSV: %s\n", output_csv);
            weight_list_free(&weights);
            free(S);
            free(C);
            free(vertex_attrs);
            free(S_initial);
            free(C_initial);
            free(S_work);
            free(C_work);
            free(interTree);
            return EXIT_FAILURE;
        }
    }

    if (selected_mode == RUN_MODE_ALL || selected_mode == RUN_MODE_SORTED_AT_END) {
        weights.size = 0;
        sorted_end_metrics = run_non_ordered_mode(
            S_work, C_work, S_initial, C_initial,
            interTree, num_vertex, num_components,
            edge_weight, time_limit_sec, &weights);
        qsort(weights.values, (size_t)weights.size, sizeof(double), compare_double_ascending);
        if (!write_weight_sequences_csv(output_csv, RUN_MODE_SORTED_AT_END, &weights)) {
            fprintf(stderr, "Failed to append sorted_at_end weights to CSV: %s\n", output_csv);
            weight_list_free(&weights);
            free(S);
            free(C);
            free(vertex_attrs);
            free(S_initial);
            free(C_initial);
            free(S_work);
            free(C_work);
            free(interTree);
            return EXIT_FAILURE;
        }
    }

    if (selected_mode == RUN_MODE_ALL || selected_mode == RUN_MODE_ORDERED) {
        weights.size = 0;
        ordered_metrics = run_ordered_mode(
            S_work, C_work, S_initial, C_initial,
            interTree, num_vertex, num_components,
            edge_weight, time_limit_sec, &weights, part_selection);
        if (!write_weight_sequences_csv(output_csv, RUN_MODE_ORDERED, &weights)) {
            fprintf(stderr, "Failed to append ordered weights to CSV: %s\n", output_csv);
            weight_list_free(&weights);
            free(S);
            free(C);
            free(vertex_attrs);
            free(S_initial);
            free(C_initial);
            free(S_work);
            free(C_work);
            free(interTree);
            return EXIT_FAILURE;
        }
    }

    printf("input=%s vertices=%d components=%d min_size=%d max_size=%d seed=%u\n",
           input_file, num_vertex, num_components, min_size, max_size, random_seed);
        if (selected_mode == RUN_MODE_ALL || selected_mode == RUN_MODE_NON_ORDERED) {
         printf("non_ordered,solutions=%lld,elapsed_ms=%.3f,status=%s,row_cap_hit=%s\n",
             non_ordered_metrics.solution_count, non_ordered_metrics.elapsed_ms,
             non_ordered_metrics.timed_out ? "timeout" : "ok",
             non_ordered_metrics.row_cap_hit ? "yes" : "no");
        }
        if (selected_mode == RUN_MODE_ALL || selected_mode == RUN_MODE_SORTED_AT_END) {
         printf("sorted_at_end,solutions=%lld,elapsed_ms=%.3f,status=%s,row_cap_hit=%s\n",
             sorted_end_metrics.solution_count, sorted_end_metrics.elapsed_ms,
             sorted_end_metrics.timed_out ? "timeout" : "ok",
             sorted_end_metrics.row_cap_hit ? "yes" : "no");
        }
        if (selected_mode == RUN_MODE_ALL || selected_mode == RUN_MODE_ORDERED) {
         printf("ordered,solutions=%lld,elapsed_ms=%.3f,status=%s,row_cap_hit=%s\n",
             ordered_metrics.solution_count, ordered_metrics.elapsed_ms,
             ordered_metrics.timed_out ? "timeout" : "ok",
             ordered_metrics.row_cap_hit ? "yes" : "no");
        }
    printf("weights_csv=%s\n", output_csv);

    weight_list_free(&weights);

    free(S);
    free(C);
    free(vertex_attrs);
    free(S_initial);
    free(C_initial);
    free(S_work);
    free(C_work);
    free(interTree);
    return EXIT_SUCCESS;
}
